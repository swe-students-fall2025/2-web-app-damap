from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import bcrypt

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Configure login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client.task_manager

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username, email):
        self.id = str(user_id)
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    user_data = db.users.find_one({'_id': ObjectId(user_id)})
    if user_data:
        return User(user_data['_id'], user_data['username'], user_data['email'])
    return None

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user_data = db.users.find_one({'username': username})
        if user_data and bcrypt.checkpw(password.encode('utf-8'), user_data['password']):
            user = User(user_data['_id'], user_data['username'], user_data['email'])
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        # Check if user already exists
        if db.users.find_one({'username': username}) or db.users.find_one({'email': email}):
            flash('Username or email already exists')
            return render_template('register.html')
        
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Create user
        user_id = db.users.insert_one({
            'username': username,
            'email': email,
            'password': hashed_password,
            'created_at': datetime.utcnow()
        }).inserted_id
        
        user = User(user_id, username, email)
        login_user(user)
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/tasks')
@login_required
def tasks():
    # Get filter and sort parameters
    filter_by = request.args.get('filter', 'all')  # all, completed, pending
    priority_filter = request.args.get('priority', 'all')  # all, high, medium, low
    category_filter = request.args.get('category', 'all')
    tag_filter = request.args.get('tag', 'all')  # Filter tasks by tags - tag filter
    sort_by = request.args.get('sort', 'newest')   # newest, oldest, alphabetical, due date
    
    # Build query based on filter
    query = {'user_id': ObjectId(current_user.id)}
    
    if filter_by == 'completed':
        query['completed'] = True
    elif filter_by == 'pending':
        query['completed'] = False
    # 'all' doesn't add any filter

    # Add priority filter
    if priority_filter != 'all':
        query['priority'] = priority_filter

    # Add category filter
    if category_filter != 'all':
        if category_filter == 'general':
            # Include tasks without category field OR with category='general'
            query['$or'] = [
                {'category': 'general'},
                {'category': {'$exists': False}}
            ]
        else:
            query['category'] = category_filter

    # Filter tasks by tag - add tag filter
    if tag_filter != 'all':
        query['tags'] = tag_filter
    
    # Determine sort order
    if sort_by == 'oldest':
        sort_order = [('created_at', 1)]  # ascending
    elif sort_by == 'alphabetical':
        sort_order = [('title', 1)]  # A-Z
    #Sort tasks by due date - sort by due date (nulls last), then by created_at
    elif sort_by == 'due_date':
        sort_order = [('due_date', 1), ('created_at', -1)]
    else:  # newest (default)
        sort_order = [('created_at', -1)]  # descending
    
    # Get filtered and sorted tasks
    tasks = list(db.tasks.find(query).sort(sort_order))

    # Filter tasks by tag - Get all unique tags for filter dropdown
    all_tags = db.tasks.distinct('tags', {'user_id': ObjectId(current_user.id)})
    
    # Filter tasks by tag - Pass tag filter & all tags to template
    return render_template('tasks.html', tasks=tasks, filter_by=filter_by, sort_by=sort_by, priority_filter=priority_filter, category_filter=category_filter, tag_filter=tag_filter, all_tags=all_tags)

@app.route('/tasks/search')
@login_required
def search_tasks():
    query = request.args.get('q', '')
    
    if query:
        # Search for tasks that contain the query in the title (case-insensitive)
        tasks = list(db.tasks.find({
            'user_id': ObjectId(current_user.id),
            'title': {'$regex': query, '$options': 'i'}
        }).sort('created_at', -1))
    else:
        # If no query, return all tasks
        tasks = list(db.tasks.find({'user_id': ObjectId(current_user.id)}).sort('created_at', -1))
    
    return render_template('tasks.html', tasks=tasks, search_query=query)

@app.route('/tasks/new', methods=['GET', 'POST'])
@login_required
def new_task():
    if request.method == 'POST':
        title = request.form['title']
        priority = request.form.get('priority', 'medium')
        category = request.form.get('category', 'general')

        # Assigning tags to tasks - Get tags from form (comma-separated)
        tags_input = request.form.get('tags', '')
        tags = [tag.strip() for tag in tags_input.split(',') if tag.strip()]

        #Adding due dates to tasks - Get due date from form
        due_date_str = request.form.get('due_date', '')
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            except ValueError:
                flash('Invalid date format')
                return render_template('new_task.html')
        
        # Get feedback from form
        feedback = request.form.get('feedback', '')
            
        # Adding Comments/Notes - Get notes from form
        notes = request.form.get('notes', '').strip()

        task_data = {
            'user_id': ObjectId(current_user.id),
            'title': title,
            'priority': priority,
            'category': category,
            'tags': tags,  # Assigning tags to tasks - store tags as array
            'due_date': due_date,  # Adding due dates to tasks - store due date
            'feedback': feedback, # Store feedback
            'needs_review': False,
            'completed': False,
            'notes': notes,  # Adding Comments/Notes - store notes
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        db.tasks.insert_one(task_data)
        flash('Task created successfully!')
        return redirect(url_for('tasks'))
    
    return render_template('new_task.html')

@app.route('/tasks/<task_id>')
@login_required
def view_task(task_id):
    task = db.tasks.find_one({'_id': ObjectId(task_id), 'user_id': ObjectId(current_user.id)})
    if not task:
        flash('Task not found')
        return redirect(url_for('tasks'))
    
    return render_template('view_task.html', task=task)

@app.route('/tasks/<task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = db.tasks.find_one({'_id': ObjectId(task_id), 'user_id': ObjectId(current_user.id)})
    if not task:
        flash('Task not found')
        return redirect(url_for('tasks'))
    
    if request.method == 'POST':
        title = request.form['title']
        completed = 'completed' in request.form
        priority = request.form.get('priority', 'medium')
        category = request.form.get('category', 'general')

        # Assigning tags to tasks - Get tags from form 
        tags_input = request.form.get('tags', '')
        tags = [tag.strip() for tag in tags_input.split(',') if tag.strip()]

        # Adding due date to tasks - Get due date from form
        due_date_str = request.form.get('due_date', '')
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            except ValueError:
                flash('Invalid date format')
                return render_template('edit_task.html', task=task)
        
        # Get feedback from form
        feedback = request.form.get('feedback', '')
            
        # Adding Comments/Notes - Get notes from form
        notes = request.form.get('notes', '').strip()

        # Get "Needs review" from form
        needs_review = 'needs_review' in request.form

        update_data = {
            'title': title,
            'completed': completed,
            'priority': priority,
            'category': category,
            'tags': tags, #Assigning tags to tasks - Update tags
            'due_date': due_date,  # Adding due date to tasks - Update due date
            'feedback': feedback, # Update feedback
            'notes': notes,  # Adding Comments/Notes - Update notes
            'needs_review': needs_review,
            'updated_at': datetime.utcnow()
        }
        
        db.tasks.update_one({'_id': ObjectId(task_id)}, {'$set': update_data})
        flash('Task updated successfully!')
        return redirect(url_for('view_task', task_id=task_id))
    
    return render_template('edit_task.html', task=task)

@app.route('/tasks/<task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    result = db.tasks.delete_one({'_id': ObjectId(task_id), 'user_id': ObjectId(current_user.id)})
    if result.deleted_count > 0:
        flash('Task deleted successfully!')
    else:
        flash('Task not found')
    
    return redirect(url_for('tasks'))

@app.route('/tasks/<task_id>/toggle', methods=['POST'])
@login_required
def toggle_task(task_id):
    task = db.tasks.find_one({'_id': ObjectId(task_id), 'user_id': ObjectId(current_user.id)})
    if task:
        new_status = not task.get('completed', False)
        db.tasks.update_one(
            {'_id': ObjectId(task_id)},
            {'$set': {'completed': new_status, 'updated_at': datetime.utcnow()}}
        )
    
    return redirect(url_for('tasks'))

if __name__ == '__main__':
    app.run(debug=True)
