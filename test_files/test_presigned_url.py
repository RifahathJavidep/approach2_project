import requests
import os

def test_secure_presigned_workflow():
    """
    Test the Choice B workflow:
    1. Call API to get a Pre-signed URL (Server-side)
    2. Use the URL to upload a file directly to S3 (Frontend simulation)
    """
    api_url = "http://localhost:8000/generate-upload-url"
    project_id = "crm_cloud"
    filename = "secure_test_file.pdf"
    
    # Create a dummy local file to upload
    local_test_file = "secure_upload_test.txt"
    with open(local_test_file, "w") as f:
        f.write("This is a test of the secure pre-signed URL workflow.")

    print(f"--- Testing Secure Pre-signed Workflow ---")
    print(f"1. Requesting Pre-signed URL from: {api_url}")
    
    payload = {
        "project_id": project_id,
        "filename": filename
    }

    try:
        # STEP 1: Get the Pre-signed URL data from our API
        response = requests.post(api_url, json=payload)
        
        if response.status_code != 200:
            print(f"   FAILED to get URL: {response.text}")
            print("   (Ensure 'python app.py' is running!)")
            return

        result = response.json()
        presigned_post = result["presigned_post"]
        s3_url = presigned_post["url"]
        fields = presigned_post["fields"]

        print(f"   SUCCESS! Got S3 Post URL: {s3_url}")

        # STEP 2: Simulate Angular uploading directly to S3
        # In a real frontend, you'd use a FormData object.
        # In Python requests, we send files and fields together.
        print(f"\n2. Uploading file directly to S3 using the Pre-signed data...")
        
        with open(local_test_file, 'rb') as f:
            files = {'file': (filename, f)}
            # AWS requires the 'fields' to be sent as form data
            upload_response = requests.post(s3_url, data=fields, files=files)

        if upload_response.status_code in [200, 204]:
            print(f"   UPLOAD SUCCESS! (Status {upload_response.status_code})")
            print(f"   File is now in S3 at: {result['s3_key']}")
            print("\nVerification Complete: Choice B workflow is working.")
        else:
            print(f"   UPLOAD FAILED: {upload_response.status_code}")
            print(f"   {upload_response.text}")

    except Exception as e:
        print(f"\nError: {e}")
    finally:
        # Clean up local dummy file
        if os.path.exists(local_test_file):
            os.remove(local_test_file)

if __name__ == "__main__":
    test_secure_presigned_workflow()
