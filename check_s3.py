import boto3
import os
from dotenv import load_dotenv

load_dotenv()

def list_project_files():
    """List all files in the projects/ directory of the S3 bucket."""
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
    
    bucket = os.getenv("S3_BUCKET_NAME", "katsuai-tcgen")
    prefix = "projects/"
    
    print(f"Checking S3 bucket: {bucket}")
    print(f"Prefix: {prefix}\n")
    
    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        
        if 'Contents' not in response:
            print("No files found in 'projects/' folder yet.")
            print("Hint: Run a POST /extract request first to generate results.")
            return

        print(f"{'Key':<60} | {'Size (bytes)':<12}")
        print("-" * 75)
        for obj in response['Contents']:
            print(f"{obj['Key']:<60} | {obj['Size']:<12}")
            
    except Exception as e:
        print(f"❌ Error connecting to S3: {e}")
        print("Check if your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env are correct.")

if __name__ == "__main__":
    list_project_files()
