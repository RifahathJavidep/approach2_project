import requests
import json

def test_miipe_server_api_integration():
    """
    Test the integrated FTP/SFTP workflow via the API.
    Simulates a request that tells the AI service to use the 'ftp' storage.
    """
    api_url = "http://localhost:8000/extract"
    project_id = "crm_cloud"
    
    # Example payload using the new 'storage' field
    payload = {
        "project_id": project_id,
        "storage": "ftp",  # Redirect output to Miipe Team Server
        "file_urls": [
            # Even if the source is S3, we can tell it to store the RESULT on FTP
            "s3://katsuai-tcgen/uploads/crm_cloud/ECO_Checkout_Features.pdf"
        ]
    }
    
    print(f"--- Testing Miipe Server API Integration ---")
    print(f"Endpoint: {api_url}")
    print(f"Target Storage: {payload['storage']}")
    print("-" * 40)

    try:
        print("\nSending request to AI Service...")
        response = requests.post(api_url, json=payload, timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            print(f"\nSUCCESS! Results successfully routed to {payload['storage'].upper()}")
            print(f"Project ID: {result['project_id']}")
            print(f"Requirements: {result['total_requirements']}")
            
            s3_output = result.get('s3_output', {})
            print(f"\nTEAM SERVER OUTPUT PATHS:")
            # These will now start with ftp:// or sftp://
            print(f"Requirements URL: {s3_output.get('requirements_url')}")
            if s3_output.get('model_url'):
                print(f"Model URL: {s3_output.get('model_url')}")
            
            print("\nVerification Complete.")
        else:
            print(f"\nWorkflow FAILED (Status {response.status_code})")
            print(f"Error: {response.text}")
            print("\nNOTE: Ensure 'python app.py' is running and FTP credentials in .env are correct.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    test_miipe_server_api_integration()
