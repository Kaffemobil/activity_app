import os
from datetime import datetime
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, jsonify
import xlsxwriter # Ensure this is imported for ExcelWriter to work if needed

# Define file paths for data storage
# In a web app, these files will be stored relative to the app's root directory
TASKS_FILE = "tasks.csv"
TYPES_FILE = "task_types.csv"
TIME_LOG_FILE = "time_log.csv"

app = Flask(__name__)

# --- Data Loading and Saving Functions (Adapted from Tkinter version) ---

def load_data(file_path, columns, date_columns=None):
    """Loads data from a CSV file, handling cases where the file might not exist or be empty."""
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            
            # Ensure all expected columns are present, fill missing with default if necessary
            for col in columns:
                if col not in df.columns:
                    df[col] = None 
            
            # Convert specified date columns to datetime objects with a consistent format
            if date_columns:
                for col in date_columns:
                    if col in df.columns:
                        # Only attempt conversion if the column actually has data
                        if not df[col].empty:
                            # Use errors='coerce' to turn unparseable dates into NaT (Not a Time)
                            df[col] = pd.to_datetime(df[col], format='%Y-%m-%d', errors='coerce')
                        else:
                            # If empty, ensure it's datetime64[ns] dtype for consistency
                            df[col] = pd.Series(dtype='datetime64[ns]')
            return df
        except pd.errors.EmptyDataError:
            # If file is empty but exists, return DataFrame with correct columns and dtypes
            empty_df = pd.DataFrame(columns=columns)
            if date_columns:
                for col in date_columns:
                    if col in empty_df.columns:
                        empty_df[col] = pd.Series(dtype='datetime64[ns]')
            return empty_df
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return pd.DataFrame(columns=columns) # Fallback to generic empty DataFrame
    else:
        # If file does not exist, return DataFrame with correct columns and dtypes
        empty_df = pd.DataFrame(columns=columns)
        if date_columns:
            for col in date_columns:
                if col in empty_df.columns:
                    empty_df[col] = pd.Series(dtype='datetime64[ns]')
        return empty_df

def save_data(df, file_path):
    """Saves a DataFrame to a CSV file."""
    try:
        df.to_csv(file_path, index=False)
    except Exception as e:
        print(f"Error saving {file_path}: {e}")

def load_tasks():
    """Loads tasks from the tasks CSV file."""
    return load_data(TASKS_FILE, ["task", "type", "date", "completed"], date_columns=['date'])

def save_tasks(df):
    """Saves tasks to the tasks CSV file."""
    save_data(df, TASKS_FILE)

def load_time_log():
    """Loads time log entries from the time log CSV file."""
    return load_data(TIME_LOG_FILE, ["task", "date", "duration_minutes"], date_columns=['date'])

def save_time_log(df):
    """Saves time log entries to the time log CSV file."""
    save_data(df, TIME_LOG_FILE)

def load_task_types():
    """Loads task types from the types CSV file."""
    types_df = load_data(TYPES_FILE, ["type"])
    return types_df["type"].tolist() if not types_df.empty else []

def save_task_type(new_type):
    """Saves a new task type to the types CSV file if it doesn't already exist."""
    types = load_task_types()
    if new_type not in types:
        with open(TYPES_FILE, "a") as f:
            f.write(f"{new_type}\n")

# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main page with the calendar and task list."""
    today = datetime.now().strftime('%Y-%m-%d')
    task_types = load_task_types()
    return render_template('index.html', selected_date=today, task_types=task_types)

@app.route('/get_tasks/<date_str>')
def get_tasks(date_str):
    """API endpoint to get tasks for a specific date."""
    df = load_tasks()
    time_df = load_time_log()

    selected_date_dt = pd.to_datetime(date_str, format='%Y-%m-%d', errors='coerce')
    tasks_for_date = df[df["date"] == selected_date_dt].sort_values(by="task").reset_index(drop=True)
    
    # Prepare tasks for JSON response
    # Convert datetime objects to string for JSON serialization
    tasks_list = []
    for _, row in tasks_for_date.iterrows():
        task_name = row["task"]
        task_type = row["type"]
        completed = row["completed"]

        # Filter time_df for the specific task and date
        duration = time_df[(time_df["task"] == task_name) & 
                            (time_df["date"] == selected_date_dt)]["duration_minutes"]
        
        hours = round(duration.sum() / 60, 2) if not duration.empty else 0

        tasks_list.append({
            "task": task_name,
            "type": task_type,
            "date": row["date"].strftime('%Y-%m-%d'), # Convert datetime to string
            "completed": completed,
            "hours": hours
        })
    return jsonify(tasks_list)

@app.route('/add_task', methods=['POST'])
def add_task():
    """API endpoint to add a new task."""
    task = request.form['task'].strip()
    task_type = request.form['type'].strip()
    selected_date_str = request.form['date'].strip()

    if not task or not task_type or not selected_date_str:
        return jsonify({"success": False, "message": "Task, type, and date are required."}), 400

    selected_date_dt = pd.to_datetime(selected_date_str, format='%Y-%m-%d', errors='coerce')

    df = load_tasks()
    new_task_df = pd.DataFrame([{
        "task": task,
        "type": task_type,
        "date": selected_date_dt,
        "completed": False
    }])
    df = pd.concat([df, new_task_df], ignore_index=True)
    save_tasks(df)
    return jsonify({"success": True, "message": "Task added successfully."})

@app.route('/mark_done', methods=['POST'])
def mark_done():
    """API endpoint to mark a task as done and log hours."""
    task_name = request.form['task_name']
    task_type = request.form['task_type']
    task_date_str = request.form['task_date']
    hours_str = request.form.get('hours_worked', '').strip()

    df = load_tasks()
    log_df = load_time_log()

    task_date_dt = pd.to_datetime(task_date_str, format='%Y-%m-%d', errors='coerce')

    # Find the task using multiple criteria
    matching_tasks_mask = (df["task"] == task_name) & \
                          (df["type"] == task_type) & \
                          (df["date"] == task_date_dt) & \
                          (df["completed"] == False) # Only mark incomplete tasks

    if matching_tasks_mask.any():
        task_index_in_df = df[matching_tasks_mask].index[0]
        df.at[task_index_in_df, "completed"] = True
        save_tasks(df)

        if hours_str:
            try:
                minutes = float(hours_str) * 60
                existing_entry_mask = (log_df["task"] == task_name) & \
                                      (log_df["date"] == task_date_dt)
                
                if existing_entry_mask.any():
                    existing_idx = log_df[existing_entry_mask].index[0]
                    log_df.at[existing_idx, "duration_minutes"] += round(minutes, 2)
                else:
                    new_log_entry_df = pd.DataFrame([{
                        "task": task_name,
                        "date": task_date_dt,
                        "duration_minutes": round(minutes, 2)
                    }])
                    log_df = pd.concat([log_df, new_log_entry_df], ignore_index=True)
                
                # Ensure 'date' column is formatted as string before saving to CSV
                # This line was added in the previous turn, ensure it's here
                log_df['date'] = log_df['date'].dt.strftime('%Y-%m-%d') 
                save_time_log(log_df)
            except ValueError:
                return jsonify({"success": False, "message": "Please enter a numeric value for hours."}), 400
            except Exception as e:
                return jsonify({"success": False, "message": f"Error logging time: {e}"}), 500
        return jsonify({"success": True, "message": "Task marked as done."})
    else:
        return jsonify({"success": False, "message": "Task not found or already completed."}), 404

@app.route('/remove_task', methods=['POST'])
def remove_task():
    """API endpoint to remove a task."""
    task_name = request.form['task_name']
    task_type = request.form['task_type']
    task_date_str = request.form['task_date']
    task_completed = request.form['task_completed'] == 'true' # Convert string to boolean

    df = load_tasks()
    task_date_dt = pd.to_datetime(task_date_str, format='%Y-%m-%d', errors='coerce')

    matching_tasks_mask = (df["task"] == task_name) & \
                          (df["type"] == task_type) & \
                          (df["date"] == task_date_dt) & \
                          (df["completed"] == task_completed)

    if matching_tasks_mask.any():
        task_index_in_df = df[matching_tasks_mask].index[0]
        df = df.drop(task_index_in_df).reset_index(drop=True)
        save_tasks(df)
        return jsonify({"success": True, "message": "Task removed successfully."})
    else:
        return jsonify({"success": False, "message": "Task not found."}), 404

@app.route('/remove_all_tasks/<date_str>', methods=['POST'])
def remove_all_tasks(date_str):
    """API endpoint to remove all tasks for a specific date."""
    df = load_tasks()
    selected_date_dt = pd.to_datetime(date_str, format='%Y-%m-%d', errors='coerce')

    initial_count = len(df)
    df = df[df["date"] != selected_date_dt].reset_index(drop=True)
    
    if len(df) == initial_count: # No tasks were removed
        return jsonify({"success": False, "message": f"No tasks found for {date_str} to remove."}), 404

    save_tasks(df)
    return jsonify({"success": True, "message": f"All tasks for {date_str} removed successfully."})

@app.route('/add_type', methods=['POST'])
def add_type():
    """API endpoint to add a new task type."""
    new_type = request.form['new_type'].strip()
    if not new_type:
        return jsonify({"success": False, "message": "Type name cannot be empty."}), 400
    
    types = load_task_types()
    if new_type not in types:
        save_task_type(new_type)
        return jsonify({"success": True, "message": "Type added successfully."})
    else:
        return jsonify({"success": False, "message": "Type already exists."}), 409

@app.route('/remove_type', methods=['POST'])
def remove_type():
    """API endpoint to remove a task type."""
    type_to_remove = request.form['type_name'].strip()
    if not type_to_remove:
        return jsonify({"success": False, "message": "Type name cannot be empty."}), 400

    types_df = load_data(TYPES_FILE, ["type"])
    
    if type_to_remove not in types_df["type"].tolist():
        return jsonify({"success": False, "message": "Type not found."}), 404

    # Check if any tasks are associated with this type
    tasks_df = load_tasks()
    if not tasks_df.empty and (tasks_df["type"] == type_to_remove).any():
        return jsonify({"success": False, "message": f"Cannot remove type '{type_to_remove}' because tasks are associated with it. Please reassign or remove those tasks first."}), 409 # Conflict

    # Remove the type
    types_df = types_df[types_df["type"] != type_to_remove].reset_index(drop=True)
    save_data(types_df, TYPES_FILE)
    
    return jsonify({"success": True, "message": f"Type '{type_to_remove}' removed successfully."})


@app.route('/get_types')
def get_types():
    """API endpoint to get all task types."""
    types = load_task_types()
    return jsonify(types)

@app.route('/get_chart_data')
def get_chart_data():
    """API endpoint to get data for charts."""
    time_df = load_time_log()
    task_df = load_tasks()

    chart_data = {}

    if not time_df.empty:
        # Hours Spent per Task
        task_hours = (time_df.groupby("task")["duration_minutes"].sum() / 60).to_dict()
        chart_data['task_hours'] = {
            'labels': list(task_hours.keys()),
            'data': list(task_hours.values())
        }

        # Daily Time Spent
        # Ensure 'date' column is datetime before grouping for consistent sorting
        time_df['date'] = pd.to_datetime(time_df['date']) 
        daily_hours = (time_df.groupby("date")["duration_minutes"].sum() / 60).sort_index().to_dict()
        chart_data['daily_time'] = {
            'labels': [date.strftime('%Y-%m-%d') for date in daily_hours.keys()], # Format date for labels
            'data': list(daily_hours.values())
        }
    else:
        chart_data['task_hours'] = {'labels': [], 'data': []}
        chart_data['daily_time'] = {'labels': [], 'data': []}

    if not task_df.empty:
        # Days Worked per Task Type
        # Ensure 'date' column is datetime before nunique
        task_df['date'] = pd.to_datetime(task_df['date'])
        days_per_type = task_df.groupby("type")["date"].nunique().to_dict()
        chart_data['days_per_type'] = {
            'labels': list(days_per_type.keys()),
            'data': list(days_per_type.values())
        }
    else:
        chart_data['days_per_type'] = {'labels': [], 'data': []}

    return jsonify(chart_data)

@app.route('/export_data/<export_format>')
def export_data(export_format):
    """API endpoint to export data as CSV or Excel."""
    tasks_df = load_tasks()
    time_log_df = load_time_log()

    if tasks_df.empty and time_log_df.empty:
        return jsonify({"success": False, "message": "No data to export."}), 404

    # For web, we'll return the file directly or a link to it
    # For simplicity, let's just return a success message for now.
    # Actual file download would involve sending a file stream.
    # This part would need more robust handling for production (e.g., temporary files, proper headers)

    from io import BytesIO
    from flask import send_file, make_response

    if export_format == "csv":
        # Create a combined CSV or separate CSVs
        # For simplicity, let's return a message for now.
        # A full implementation would involve zipping or separate downloads.
        # Example of sending a single CSV:
        # csv_output = tasks_df.to_csv(index=False)
        # response = make_response(csv_output)
        # response.headers["Content-Disposition"] = "attachment; filename=tasks.csv"
        # response.headers["Content-type"] = "text/csv"
        # return response
        return jsonify({"success": True, "message": "CSV export initiated. (Files would be downloaded in a full implementation)"})

    elif export_format == "excel":
        excel_output = BytesIO()
        with pd.ExcelWriter(excel_output, engine='xlsxwriter') as writer:
            tasks_df.to_excel(writer, sheet_name="Tasks", index=False)
            time_log_df.to_excel(writer, sheet_name="Time Log", index=False)
        excel_output.seek(0)
        
        # Example of sending an Excel file:
        # response = make_response(excel_output.getvalue())
        # response.headers["Content-Disposition"] = "attachment; filename=productivity_data.xlsx"
        # response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        # return response
        return jsonify({"success": True, "message": "Excel export initiated. (File would be downloaded in a full implementation)"})

    return jsonify({"success": False, "message": "Invalid export format."}), 400


if __name__ == '__main__':
    # Create data files if they don't exist to prevent errors on first run
    for file_path, cols, date_cols in [
        (TASKS_FILE, ["task", "type", "date", "completed"], ['date']),
        (TYPES_FILE, ["type"], []),
        (TIME_LOG_FILE, ["task", "date", "duration_minutes"], ['date'])
    ]:
        if not os.path.exists(file_path):
            df = pd.DataFrame(columns=cols)
            if date_cols:
                for col in date_cols:
                    if col in df.columns:
                        df[col] = pd.Series(dtype='datetime64[ns]')
            save_data(df, file_path)

    app.run(debug=True) # Run in debug mode for development
