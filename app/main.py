from fastapi import FastAPI, HTTPException, Query, Form, Request, status, Body, APIRouter
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
import mysql.connector
from mysql.connector import Error
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import os
from dotenv import load_dotenv
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional, List, Dict
from passlib.context import CryptContext
import uuid
import hashlib
from contextlib import asynccontextmanager
import app.database.connection as db


templates = Jinja2Templates(directory="app")
class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    completed: Optional[bool] = False

class TaskCreate(TaskBase):
    pass

class Task(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield

app = FastAPI(
    title="Task Management API",
    description="A Rosetta Stone CRUD API for managing tasks",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("app/index.html")

@app.get("/login", response_class=HTMLResponse)
async def read_login():
    return FileResponse("app/login.html")
@app.post("/login")
async def userlogin(request: Request, email: str = Form(...), password: str = Form(...)):
    from app.database import create_session, get_user_by_id
    """Login endpoint to authenticate the user."""

    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    try:
        cursor = conn.cursor()
        # Query to find the user by email
        cursor.execute("SELECT id, email, password_hash FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        # Check if the user exists
        if user is None:
            raise HTTPException(status_code=400, detail="Invalid email or password")

        # Extract the user data (id, email, password_hash)
        user_id, user_email, stored_password_hash = user


        # Verify the password
        pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
        if not pwd_context.verify(password, stored_password_hash):
            return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid email or password"})
        session_id = str(uuid.uuid4())
        session = await create_session(user_id, session_id)
        if not session:
            response = RedirectResponse(url=f"/login", status_code=302)
            return response
        response = RedirectResponse(url=f"/wardrobe", status_code=302)
        response.set_cookie(key="sessionId", value=session_id, httponly=True, max_age=3600)
        return response

    except Error as e:
        raise HTTPException(status_code=500, detail=f"Error during database operation: {e}")

    finally:
        cursor.close()
        conn.close()

@app.post("/tasks/", response_model=Task)
async def create_task(task: TaskCreate):
    conn = db.get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = "INSERT INTO tasks (title, description, completed) VALUES (%s, %s, %s)"
        values = (task.title, task.description, task.completed)
        cursor.execute(query, values)
        conn.commit()
        
        # Get the created task
        task_id = cursor.lastrowid
        cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        new_task = cursor.fetchone()
        return new_task
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/tasks/", response_model=List[Task])
async def read_tasks():
    conn = db.get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM tasks")
        tasks = cursor.fetchall()
        return tasks
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/tasks/{task_id}", response_model=Task)
async def read_task(task_id: int):
    conn = db.get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        task = cursor.fetchone()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: int, task: TaskCreate):
    conn = db.get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
        UPDATE tasks 
        SET title = %s, description = %s, completed = %s
        WHERE id = %s
        """
        values = (task.title, task.description, task.completed, task_id)
        cursor.execute(query, values)
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
            
        cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        updated_task = cursor.fetchone()
        return updated_task
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    conn = db.get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return {"message": "Task deleted successfully"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close() 

