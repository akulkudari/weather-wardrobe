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
import httpx

AITEXT_API_URL = "https://ece140-wi25-api.frosty-sky-f43d.workers.dev/api/v1/ai/complete"

templates = Jinja2Templates(directory="app")
class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    completed: Optional[bool] = False

class TaskCreate(TaskBase):
    pass

class ClothingItem(BaseModel):
    clothingType: str
    clothingColor: str
    clothingSize: str
    
class SensorItem(BaseModel):
    device_type: str
    mac_address: str
    device_name: str

class SensorUpdate(BaseModel):
    old: SensorItem
    new: SensorItem

class ClothingUpdate(BaseModel):
    oldClothing: ClothingItem
    newClothing: ClothingItem

class SensorData(BaseModel):
   value: float
   unit: str
   timestamp: Optional[str] = None
   mac_address: str

class Task(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True



def insert_default_user():
    conn = db.get_db_connection()
    if conn is None:
        return

    try:
        cursor = conn.cursor()
        username = "a"
        email = "a@k.ul"
        password = "a"  # Change this to a secure password
        location = "La Jolla"

        # Hash password before inserting (SHA-256 used here)
        pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
        hashed_password = pwd_context.hash(password)

        cursor.execute(
                "INSERT INTO users (username, email, password_hash, location) VALUES (%s, %s, %s, %s)",
                (username, email, hashed_password, location)
            )
        conn.commit()
        print("Default user added successfully.")
    except Error as e:
        print(f"Error: {e}")

    finally:
        cursor.close()
        conn.close()
def generate_unique_hash(field1, field2, field3, field4):
    data_string = f"{field1}|{field2}|{field3}|{field4}"  # Concatenate fields
    return hashlib.sha256(data_string.encode()).hexdigest() 
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

@app.on_event("startup")
async def startup_event():
   """Runs at startup to seed the database."""
   db.create_tables()
   print("this runs everytime")
   await db.setup_database()
   insert_default_user()

async def authenticate_user(request: Request):
    session_id = request.cookies.get("sessionId")
    if not session_id:
        raise HTTPException(status_code=401, detail="Unauthorized: No session ID provided")
    
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")  

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM sessions WHERE id = %s", (session_id,))
        valid_session = cursor.fetchone()

        if not valid_session:
            return None  # Instead of raising HTTPException, return None for handling

        user_id = valid_session[0]  # Extract the user_id from the result
        print(user_id)
        user = await db.get_user_by_id(user_id)  # Ensure this is async; otherwise, remove 'await'
        
        if not user:
            return None  # No valid user found
        
        return user_id  # Return authenticated user_id

    finally:
        cursor.close()
        conn.close()

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("app/index.html")
    
@app.get("/api/{sensor_type}/count")
def get_sensor_count(sensor_type: str):
   """Returns the number of rows for a given sensor type."""
   if sensor_type not in ["temperature", "humidity", "light"]:
       raise HTTPException(status_code=404, detail="Invalid sensor type")
   
   conn = db.get_db_connection()
   cursor = conn.cursor()

   query = f"SELECT COUNT(*) FROM {sensor_type}"
   cursor.execute(query)
   count = cursor.fetchone()[0]

   cursor.close()
   conn.close()

   return count

@app.get("/api/{sensor_type}")
def get_all_sensor_data(
    sensor_type: str,
    order_by: Optional[str] = Query(None, alias="order-by"),
    start_date: Optional[str] = Query(None, alias="start-date"),
    end_date: Optional[str] = Query(None, alias="end-date")
):
    """Fetch sensor data with optional filtering and sorting."""
    if sensor_type not in ["temperature", "humidity", "light"]:
        raise HTTPException(status_code=404, detail="Invalid sensor type")

    connection = db.get_db_connection()
    connectionCursor = connection.cursor(dictionary=True)
    query = f"SELECT * FROM {sensor_type} WHERE 1=1"
    params = []
    if start_date:
        query += " AND timestamp >= %s"
        params.append(start_date)
    if end_date:
        query += " AND timestamp <= %s"
        params.append(end_date)
    if order_by in ["value", "timestamp"]:
        query += f" ORDER BY {order_by} ASC"
    connectionCursor.execute(query, params)
    data = connectionCursor.fetchall()
    connectionCursor.close()
    connection.close()

    # Convert timestamp fields to the expected format
    for record in data:
        ts = record.get("timestamp")
        if ts and isinstance(ts, datetime):
            record["timestamp"] = ts.strftime("%Y-%m-%d %H:%M:%S")
    return data

@app.post("/api/{sensor_type}")
def insert_sensor_data(sensor_type: str, data: SensorData):
   """Insert new sensor data."""
   if sensor_type not in ["temperature", "humidity", "light"]:
       raise HTTPException(status_code=404, detail="Invalid sensor type")
   connection = db.get_db_connection()
   connectionCursor = connection.cursor()
   timestamp = data.timestamp if data.timestamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
   query = f"INSERT INTO {sensor_type} (value, unit, timestamp) VALUES (%s, %s, %s)"
   connectionCursor.execute(query, (data.value, data.unit, timestamp))
   connection.commit()
   inserted_id = connectionCursor.lastrowid
   connectionCursor.close()
   connection.close()
   return {"id": inserted_id}

@app.get("/api/{sensor_type}/{id}")
def get_sensor_data(sensor_type: str, id: int):
   """Get a specific sensor reading by ID."""
   if sensor_type not in ["temperature", "humidity", "light"]:
       raise HTTPException(status_code=404, detail="Invalid sensor type")
   connection = db.get_db_connection()
   connectionCursor = connection.cursor(dictionary=True)
   query = f"SELECT * FROM {sensor_type} WHERE id = %s"
   connectionCursor.execute(query, (id,))
   data = connectionCursor.fetchone()
   connectionCursor.close()
   connection.close()
   if not data:
       raise HTTPException(status_code=404, detail="Data not found")
   return data

@app.put("/api/{sensor_type}/{id}")
def update_sensor_data(sensor_type: str, id: int, data: SensorData):
   """Update an existing sensor reading."""
   if sensor_type not in ["temperature", "humidity", "light"]:
       raise HTTPException(status_code=404, detail="Invalid sensor type")
   connection = db.get_db_connection()
   connectionCursor = connection.cursor()
   updates = []
   params = []
   if data.value is not None:
       updates.append("value = %s")
       params.append(data.value)
   if data.unit:
       updates.append("unit = %s")
       params.append(data.unit)
   if data.timestamp:
       updates.append("timestamp = %s")
       params.append(data.timestamp)
   if data.mac_address:
       updates.append("mac_address = %s")
       params.append (data.mac_address)
   if not updates:
       raise HTTPException(status_code=400, detail="No fields to update")
   params.append(id)
   query = f"UPDATE {sensor_type} SET {', '.join(updates)} WHERE id = %s"
   connectionCursor.execute(query, params)
   connection.commit()
   connectionCursor.close()
   connectionCursor.close()
   return {"message": "Updated successfully"}

@app.delete("/api/{sensor_type}/{id}")
def delete_sensor_data(sensor_type: str, id: int):
   """Delete a sensor reading."""
   if sensor_type not in ["temperature", "humidity", "light"]:
       raise HTTPException(status_code=404, detail="Invalid sensor type")
   
   connection = db.get_db_connection()
   connectionCursor = connection.cursor()

   query = f"DELETE FROM {sensor_type} WHERE id = %s"
   connectionCursor.execute(query, (id,))

   connection.commit()
   connectionCursor.close()
   connection.close()
   return {"message": "Deleted successfully"}

@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    return FileResponse("app/dashboard.html")

@app.get("/image")
async def image_page(request: Request):
    user_id = authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse("app/imagegen.html")

@app.post("/ai-image")
async def generate_ai_image(request: Request):
    data = await request.json()
    prompt = data.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")
    width = data.get("width", 512)
    height = data.get("height", 512)
    user_id = authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)
    conn = db.get_db_connection()
    cursor = conn.cursor()
    try: 
        cursor.execute("SELECT email, PID FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        API_URL = "https://ece140-wi25-api.frosty-sky-f43d.workers.dev/api/v1/ai/image"
        payload = {
            "email": user[0],
            "PID": user[1],
            "prompt": prompt,
            "width": width,
            "height": height
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        return response.json()
    except Exception as e:
        import traceback
        print("Database Error:", traceback.format_exc())  # Log error details
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    finally:
        cursor.close()
        conn.close()    
@app.get("/user_info")
async def get_user_info(request: Request):
    """
    Fetch user info from the users table.
    
    :param request: The server request.
    :return: A JSON response containing user's data.
    """
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)
    
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, location, PID, created_at FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()  # 🔹 Fetch only ONE user
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # 🔹 Convert datetime field to string
        user_data = {
            "id": user[0],
            "username": user[1],
            "email": user[2],
            "location": user[3],
            "PID": user[4],
            "created_at": user[5].isoformat() if isinstance(user[4], datetime) else None
        }

        return JSONResponse(content=user_data)

    except Exception as e:
        import traceback
        print("Database Error:", traceback.format_exc())  # Log error details
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    finally:
        cursor.close()
        conn.close()

@app.get("/ai", response_class=HTMLResponse)
async def ai(request: Request):
    user_id = authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    return FileResponse("app/aiassistant.html")     



@app.get("/clothes")
async def get_clothes(request: Request):
    """
    Fetch all clothing items for a given user_id from the clothes table.
    
    :param user_id: The ID of the user whose wardrobe items should be retrieved.
    :return: A JSON response containing clothing data.
    """
    user_id = await authenticate_user(request)     # authenticate user first
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    try:
        cursor = conn.cursor(dictionary=True)  # Ensures results are returned as dictionaries
        query = "SELECT * FROM clothes WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        clothes = cursor.fetchall()
        if clothes:  # Check if clothes is not empty
            print("Clothes retrieved successfully:", clothes)
        else:
            print("No clothes found for this user.")
        return JSONResponse(content=clothes)  # Return data as JSON
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    

    finally:
        cursor.close()
        conn.close()

@app.get("/devices")
async def get_devices(request: Request):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    def serialize_row(row):
        return {
            "id": row[0],
            "user_id": row[1],
            "device_name": row[2],
            "device_type": row[3],
            "mac_address": row[4],
            "created_at": row[5].isoformat() if isinstance(row[5], datetime) else row[5]
        }

    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM devices WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        devices = [serialize_row(row) for row in cursor.fetchall()]

        if not devices:
            return {"message": "No devices found for this user."}

        return devices  # FastAPI will automatically return JSON

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    finally:
        cursor.close()
        conn.close()

@app.post("/wardrobe")
async def add_to_wardrobe(
    request: Request,
    item: ClothingItem
):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        cursor = conn.cursor()

        # Ensure the table exists
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS clothes (
            clothing_id VARCHAR(255) NOT NULL PRIMARY KEY,
            user_id INT NOT NULL,
            clothing_type VARCHAR(255) NOT NULL,
            clothing_color CHAR(7) NOT NULL,
            clothing_size VARCHAR(10) NOT NULL, 
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """)
        conn.commit()
        clothing_id = generate_unique_hash(user_id, item.clothingType, item.clothingColor, item.clothingSize)
        # Insert new clothing item
        cursor.execute("""
        INSERT INTO clothes (clothing_id, user_id, clothing_type, clothing_color, clothing_size)
        VALUES (%s, %s, %s, %s, %s);
        """, (clothing_id, user_id, item.clothingType, item.clothingColor, item.clothingSize))
        conn.commit()
        cursor.execute("""
        SELECT * FROM clothes 
        WHERE clothing_id = %s
        """, (clothing_id,)) 
        result = cursor.fetchone()  # Store the fetched result
        if result:  
            print("Insertion successful")
            return RedirectResponse(url = "/wardrobe", status_code=201)
        else:
            print("Insertion failed")
        cursor.close()
        
    except mysql.connector.errors.InternalError as e:
        return JSONResponse(content={"error": "Unread result found. Please check query execution order."}, status_code=500)

    except Exception as e:
        print(f"❌ Error updating clothing: {e}")
        return JSONResponse(content={"error": f"Database error: {str(e)}"}, status_code=500)

    finally:
        if conn:
            conn.close()  # Ensure connection is closed after use

@app.get("/wardrobe")
async def read_wardrobe(request: Request, json_response: bool = False):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    if user_id:
        return FileResponse("app/wardrobe.html")

@app.put("/wardrobe")
async def update_clothing(request: Request, update_data: ClothingUpdate):
    """Update an existing clothing item in the database."""
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        cursor = conn.cursor()

        # Extract old and new values
        old = update_data.oldClothing
        new = update_data.newClothing
        old_clothing_id = generate_unique_hash(user_id, old.clothingType, old.clothingColor, old.clothingSize)
        new_clothing_id = generate_unique_hash(user_id, new.clothingType, new.clothingColor, new.clothingSize)
        # Ensure the old clothing exists
        old_clothing_id = str(old_clothing_id)
        cursor.execute("SELECT * FROM clothes WHERE clothing_id = %s AND user_id = %s", (old_clothing_id, user_id))
        existing_clothing = cursor.fetchone()
        if existing_clothing:
            print("item found")
        if not existing_clothing:
            raise HTTPException(status_code=404, detail="Clothing item not found")
        # Update the clothing item
        update_query = """
        UPDATE clothes 
        SET clothing_id = %s, clothing_type = %s, clothing_color = %s, clothing_size = %s
        WHERE clothing_id = %s AND user_id = %s
        """
        cursor.execute(update_query, (new_clothing_id, new.clothingType, new.clothingColor, new.clothingSize, old_clothing_id, user_id))
        
        conn.commit()
        return {"message": "Clothing updated successfully"}

    except Exception as e:
        print(f"❌ Error updating clothing: {e}")  # Print the actual error
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    finally:
        cursor.close()
        conn.close()

@app.delete("/wardrobe")
async def delete_clothing(request: Request,  item: ClothingItem):
    """Delete a clothing item from the database."""
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        cursor = conn.cursor()
        
        # Generate the unique clothing ID
        clothing_id = generate_unique_hash(user_id, item.clothingType, item.clothingColor, item.clothingSize)
        print(item.clothingColor)
        print(item.clothingType)
        print(item.clothingSize)
        print(user_id)


        clothing_id = str(clothing_id)
        print(clothing_id)
        # Check if the clothing item exists
        cursor.execute("SELECT * FROM clothes WHERE clothing_id = %s AND user_id = %s", (clothing_id, user_id))
        existing_clothing = cursor.fetchone()
        
        if not existing_clothing:
            raise HTTPException(status_code=404, detail="Clothing item not found")
        
        # Delete the clothing item
        delete_query = "DELETE FROM clothes WHERE clothing_id = %s AND user_id = %s"
        cursor.execute(delete_query, (clothing_id, user_id))
        conn.commit()
        
        return {"message": "Clothing item deleted successfully"}
    
    except Exception as e:
        print(f"❌ Error deleting clothing: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    
    finally:
        cursor.close()
        conn.close()

@app.post("/getairesponse")
async def getAIResponse(request: Request, email: str = Form(...), PID: str = Form(...), prompt: str = Form(...)):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    try:
        # Send request to external AI API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                AITEXT_API_URL,
                headers={
                    "email": email,
                    "pid": PID,
                    "Content-Type": "application/json"
                },
                json={"prompt": prompt}  # Sending prompt as JSON body
            )

        # Handle response
        if response.status_code == 200:
            response_json = response.json()
            ai_response = response_json.get("result", {}).get("response", "No response found")
            return JSONResponse(content={"response": ai_response})
        else:
            return JSONResponse(
                content={"error": f"AI API error: {response.text}"},
                status_code=response.status_code
            )
    except httpx.ReadTimeout:
        return JSONResponse(status_code=504, content={"error": "AI response took too long."})
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        return JSONResponse(
            content={"error": f"Internal server error: {str(e)}"},
            status_code=500
        )

@app.get("/login", response_class=HTMLResponse)
async def read_login():
    return FileResponse("app/login.html")

@app.get("/temperatures")
async def get_temp():
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        connectionCursor = conn.cursor(dictionary=True)  # Use dictionary mode for JSON response
        query = "SELECT * FROM temperatures"
        connectionCursor.execute(query)
        result = connectionCursor.fetchall()  # Fetch all records
        return result
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")
    finally:
        connectionCursor.close()
        conn.close()

@app.get("/temperatures/{mac_address}")
async def get_temp_by_mac(mac_address: str):
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        connectionCursor = conn.cursor(dictionary=True)  # Use dictionary mode for JSON response
        query = "SELECT * FROM temperatures WHERE mac_address = %s"
        connectionCursor.execute(query, (mac_address,))
        result = connectionCursor.fetchall()  # Fetch all records
        
        if not result:
            raise HTTPException(status_code=404, detail=f"No temperature data found for MAC address: {mac_address}")

        return result
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")
    finally:
        connectionCursor.close()
        conn.close()


@app.post("/update_temperature_reading")
async def update_temp(data: SensorData):
    # user_id = await authenticate_user(request)
    # if user_id is None:
        # return RedirectResponse(url="/login", status_code = 302)
    db.create_temperatures_table() 
    conn = db.get_db_connection()
    if conn is None:
        return "Database connection error"
    try:
        connectionCursor = conn.cursor()
        timestamp = data.timestamp if data.timestamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        query = f"INSERT INTO temperatures (value, unit, mac_address, timestamp) VALUES (%s, %s, %s, %s)"
        connectionCursor.execute(query, (data.value, data.unit, data.mac_address, timestamp))
        conn.commit()
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Error during database operation: {e}")

@app.post("/login")
async def userlogin(request: Request, email: str = Form(...), password: str = Form(...)):
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
        session = await db.create_session(user_id, session_id)
        if not session:
            response = RedirectResponse(url=f"/login", status_code=302)
            return response
        response = RedirectResponse(url=f"/dashboard", status_code=302)
        response.set_cookie(key="sessionId", value=session_id, httponly=True, max_age=3600)
        return response

    except Error as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Error during database operation: {e}")

    finally:
        cursor.close()
        conn.close()

@app.get("/signup", response_class=HTMLResponse)
async def read_signup():
    return FileResponse("app/signup.html")

@app.post("/signup")
async def signup(username: str = Form(...), email: str = Form(...), password: str = Form(...), PID: str = Form(...), location: str = Form(...)):
    conn = db.get_db_connection()
    if conn is None:
        return "Database connection error"
    try:
        cursor = conn.cursor()
        create_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            PID VARCHAR(10) NOT NULL,
            location VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        cursor.execute(create_table_query)
        print("Table 'users' created successfully!")
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Hash the password
        pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
        hashed_password = pwd_context.hash(password)
        print("we got to here")
        # Insert the new user into the 'users' table
        insert_query = """
        INSERT INTO users (username, email, password_hash, PID, location)
        VALUES (%s, %s, %s, %s, %s);
        """
        cursor.execute(insert_query, (username, email, hashed_password, PID, location))
        conn.commit()
        response = RedirectResponse(url = "/login", status_code = 302)
        return response 
    
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Error during database operation: {e}")
    
    finally:
        cursor.close()
        conn.close()


@app.post("/profile")
async def add_device(request: Request, device: SensorItem):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        cursor = conn.cursor()
        # Ensure the devices table exists
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id VARCHAR(36) PRIMARY KEY,
            user_id INT NOT NULL,
            device_name VARCHAR(255) NOT NULL,
            device_type VARCHAR(255) NOT NULL,
            mac_address VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
        conn.commit()
        device_id = generate_unique_hash(user_id, device.device_name, device.mac_address, device.device_type)
        # Insert new device
        cursor.execute("""
        INSERT INTO devices (id, user_id, device_type, mac_address, device_name)
        VALUES (%s, %s, %s, %s, %s);
        """, (device_id, user_id, device.device_type, device.mac_address, device.device_name))
        print(device_id)
        conn.commit()
        return {"message": "Device added successfully"}

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@app.get("/profile")
async def read_profile(request: Request):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        return FileResponse("app/profile.html")
    except Exception as e:
        print(f"❌ Error reaching profile: {e}")
        return JSONResponse(content={"error": f"Database error: {str(e)}"}, status_code=500) 

@app.put("/profile")
async def update_device(request: Request, update: SensorUpdate):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        cursor = conn.cursor()

        old_device_id = generate_unique_hash(user_id, update.old.device_name, update.old.mac_address, update.old.device_type)
        
        print(old_device_id)
        
        new_device_id = generate_unique_hash(user_id, update.new.device_name, update.new.mac_address, update.new.device_type)

        # Check if the old device exists
        cursor.execute("SELECT * FROM devices WHERE id = %s AND user_id = %s", (old_device_id, user_id))
        existing_device = cursor.fetchone()

        if not existing_device:
            raise HTTPException(status_code=404, detail="Device not found")

        # Update the device
        cursor.execute("""
        UPDATE devices 
        SET id = %s, device_type = %s, mac_address = %s, device_name = %s
        WHERE id = %s AND user_id = %s
        """, (new_device_id, update.new.device_type, update.new.mac_address, update.new.device_name, old_device_id, user_id))
        
        conn.commit()
        return {"message": "Device updated successfully"}

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    finally:
        cursor.close()
        conn.close()

@app.delete("/profile")
async def delete_sensor(request: Request, sensor: SensorItem = Body(...)):
    user_id = await authenticate_user(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code = 302)
    """Delete a sensor from the database."""
    conn = db.get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        cursor = conn.cursor()
        sensor_id = generate_unique_hash(user_id, sensor.device_name, sensor.mac_address, sensor.device_type)
        sensor_id = str(sensor_id)
        cursor.execute("SELECT * FROM devices WHERE id = %s AND user_id = %s", (sensor_id, user_id))
        existing_sensor = cursor.fetchone()
        
        if not existing_sensor:
            raise HTTPException(status_code=404, detail="Sensor not found")
        
        cursor.execute("DELETE FROM devices WHERE id = %s AND user_id = %s", (sensor_id, user_id))
        conn.commit()
        
        return {"message": "Sensor deleted successfully"}
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Database Error:", error_details)  # Log full error details
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
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

