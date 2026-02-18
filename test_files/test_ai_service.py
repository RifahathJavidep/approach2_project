import requests
import json
import time

def test_ai_service_s3_flow():
    """
    Tests the complete AI Service workflow:
    1. Send S3 URL to /extract endpoint
    2. Service downloads from S3, processes, and uploads back to S3
    3. Verify the response contains the new S3 output URL
    """
    
    # 1. Configuration
    api_url = "http://localhost:8000/extract"
    project_id = "crm_cloud"
    
    # Use the S3 URL we generated in the previous step
    # Make sure you have run test_s3_upload.py first!
    s3_file_url = "s3://katsuai-tcgen/uploads/crm_cloud/ECO_Checkout_Features.pdf"
    
    payload = {
        "project_id": project_id,
        "file_urls": [s3_file_url]
    }
    
    print(f"--- Testing AI Service Workflow ---")
    print(f"Endpoint: {api_url}")
    print(f"Input S3 URL: {s3_file_url}")
    print("-" * 34)

    try:
        # 2. Send request to the AI Service
        print("\nSending request to AI Service (this may take 30-60 seconds)...")
        start_time = time.time()
        
        response = requests.post(api_url, json=payload, timeout=120)
        
        duration = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n--- Workflow Success! (took {duration:.1f}s) ---")
            print(f"Status: {result['status']}")
            print(f"Project ID: {result['project_id']}")
            print(f"Requirements Extracted: {result['total_requirements']}")
            
            # 3. Show the output S3 URLs
            s3_output = result.get('s3_output', {})
            print(f"\nRESULT UPLOADED TO S3:")
            print(f"Output Requirements URL: {s3_output.get('requirements_url')}")
            if s3_output.get('model_url'):
                print(f"Output Model URL: {s3_output.get('model_url')}")
            
            print("\nVerification: You can now check your S3 bucket for the 'projects/crm_cloud/output/' directory.")
            print("---------------------------------------")
        else:
            print(f"\nWorkflow FAILED (Status {response.status_code})")
            print(f"Error: {response.text}")
            print("\nNOTE: Make sure the FastAPI server is running! (Run 'python app.py' in a separate terminal)")

    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to the AI Service.")
        print("Please ensure the server is running by executing 'python app.py' in another terminal.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    test_ai_service_s3_flow()
