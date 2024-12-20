from flask import Flask, request, jsonify
import requests
import queue
import threading
import time
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)

request_queue = queue.Queue()
is_processor_running = False
processing_lock = threading.Lock()

def process_request(phone, tracking):
    # First API call - Update order
    update_url = "https://app.noest-dz.com/api/public/update/order"
    update_payload = {
        "api_token": os.getenv('API_TOKEN'),
        "user_guid": os.getenv('USER_GUID'),
        "tracking": tracking,
        "tel": phone
    }

    try:
        update_response = requests.post(update_url, json=update_payload)
        
        if update_response.status_code != 200:
            return {
                "error": "Invalid tracking ID or server error",
                "update_status": update_response.status_code,
                "update_response": update_response.text
            }
            
        update_data = update_response.json()
        if "error" in update_data or "success" not in update_data or not update_data.get("success"):
            return {
                "error": "Invalid tracking ID",
                "update_status": update_response.status_code,
                "update_response": update_data
            }

        time.sleep(3)
        
        # Second API call - Get scoring
        scoring_url = "https://app.noest-dz.com/get/scoring"
        scoring_payload = {"phones[]": phone}
        scoring_headers = {
            "origin": "https://app.noest-dz.com",
            "referer": "https://app.noest-dz.com/validation/orders",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "x-csrf-token": os.getenv('CSRF_TOKEN'),
            "x-requested-with": "XMLHttpRequest"
        }
        scoring_cookies = {
            "noest_express_session": os.getenv('SESSION_COOKIE'),
        }

        scoring_response = requests.post(
            scoring_url,
            data=scoring_payload,
            headers=scoring_headers,
            cookies=scoring_cookies
        )

        if scoring_response.status_code != 200:
            return {
                "update_status": update_response.status_code,
                "update_response": update_data,
                "error": "Invalid phone number or scoring error",
                "scoring_status": scoring_response.status_code,
                "scoring_response": scoring_response.text
            }

        scoring_data = scoring_response.json()
        if not scoring_data or "error" in scoring_data:
            return {
                "update_status": update_response.status_code,
                "update_response": update_data,
                "error": "Invalid phone number",
                "scoring_status": scoring_response.status_code,
                "scoring_response": scoring_data
            }

        return {
            "update_status": update_response.status_code,
            "update_response": update_data,
            "scoring_status": scoring_response.status_code,
            "scoring_response": scoring_data
        }

    except requests.RequestException as e:
        return {
            "error": f"Network or server error: {str(e)}"
        }

def request_processor():
    global is_processor_running
    while True:
        try:
            phone, tracking, result_queue = request_queue.get(timeout=60)
            
            try:
                result = process_request(phone, tracking)
                result_queue.put(("success", result))
            except Exception as e:
                result_queue.put(("error", str(e)))
                
            request_queue.task_done()
            
        except queue.Empty:
            with processing_lock:
                is_processor_running = False
            break

@app.route('/update_and_get_scoring/<phone>/<tracking>', methods=['GET'])
def update_and_get_scoring(phone, tracking):
    global is_processor_running
    
    # Basic input validation
    if not phone or not tracking:
        return jsonify({"error": "Phone and tracking ID are required"}), 400
        
    if not phone.isdigit() or len(phone) < 9 or len(phone) > 10:
        return jsonify({"error": "Invalid phone number format"}), 400
    
    result_queue = queue.Queue()
    request_queue.put((phone, tracking, result_queue))
    
    with processing_lock:
        if not is_processor_running:
            is_processor_running = True
            threading.Thread(target=request_processor, daemon=True).start()
    
    try:
        status, result = result_queue.get(timeout=30)
        
        if status == "error":
            return jsonify({"error": result}), 500
            
        if "error" in result:
            return jsonify(result), 400
            
        return jsonify(result)
    
    except queue.Empty:
        return jsonify({"error": "Request timed out"}), 504

# Add a health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # Verify that all required environment variables are present
    required_vars = ['USER_GUID', 'API_TOKEN', 'CSRF_TOKEN',
                    'SESSION_COOKIE']
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
        
    app.run(host='0.0.0.0', debug=True, port=5000)