import os
import sys
from s3_utils import upload_to_s3, get_bucket_name

def test_frontend_simulated_upload():
    """
    Simulates a frontend upload of a PDF or PPTX to S3.
    """
    # 1. Define the local file to upload
    # We'll use a sample file from the input directory if it exists
    sample_file = "input/ecommerce_gateway/ECO_Checkout_Features.pdf"
    
    if not os.path.exists(sample_file):
        print(f"Error: Sample file {sample_file} not found.")
        print("Please make sure you are running this from the project root.")
        return

    # 2. Define where it should go in S3 (The "Directory" or Key)
    # Usually you'd use a project-specific path
    project_name = "crm_cloud"
    filename = os.path.basename(sample_file)
    s3_key = f"uploads/{project_name}/{filename}"

    print(f"--- Simulating Frontend Upload ---")
    print(f"Local File: {sample_file}")
    print(f"Target S3 Key: {s3_key}")
    print("-" * 34)

    try:
        # 3. Perform the upload
        s3_url = upload_to_s3(sample_file, s3_key, content_type="application/pdf")
        
        # 4. Get the Bucket name and construct URLs
        bucket = get_bucket_name()
        region = os.getenv("AWS_REGION", "us-east-1")
        
        # HTTPS Public/Constructed URL
        https_url = f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
        
        # Directory URL (The prefix)
        directory_url = f"s3://{bucket}/uploads/{project_name}/"

        print("\n--- Upload Successful! ---")
        print(f"S3 Protocol URL: {s3_url}")
        print(f"HTTPS Download URL: {https_url}")
        print(f"S3 Directory Prefix: {directory_url}")
        print("---------------------------")
        
    except Exception as e:
        print(f"\nUpload Failed: {e}")

if __name__ == "__main__":
    test_frontend_simulated_upload()
