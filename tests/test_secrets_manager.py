
import os
import sys
import logging
from pathlib import Path

# Add project root to sys.path to allow imports from utils
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
from utils.secrets import get_secret, _cache

# Load .env file for local testing
load_dotenv()

# Configure logging to see the output from secrets.py
logging.basicConfig(level=logging.INFO)

def test_secrets_manager():
    print("\n" + "="*50)
    print("PRISM SECRETS MANAGER TEST")
    print("="*50)

    # 1. Test Local Environment Fallback (from .env)
    print("\n[1] Testing Local Environment Fallback...")
    # These must exist in your .env for this part to pass
    test_keys = ["GROQ_API_KEY", "AWS_REGION", "S3_BUCKET_NAME"]
    
    for key in test_keys:
        try:
            val = get_secret(key)
            # Mask the secret for security
            masked = val[:5] + "*" * (len(val) - 5) if val else "NONE"
            print(f"  ✓ Found '{key}': {masked}")
        except Exception as e:
            print(f"  ✗ Failed to find '{key}': {e}")

    # 2. Test Default Value Logic
    print("\n[2] Testing Default Value Logic...")
    default_test = get_secret("NON_EXISTENT_KEY", default="default_fallback_value")
    if default_test == "default_fallback_value":
        print("  ✓ Correctly returned default value for missing key.")
    else:
        print(f"  ✗ Failed: Expected 'default_fallback_value', got '{default_test}'")

    # 3. Test AWS Secrets Manager Connectivity
    print("\n[3] Testing AWS Secrets Manager Connectivity...")
    # NOTE: This requires valid AWS credentials to be configured (AWS_ACCESS_KEY_ID, etc.)
    # or to be running in an environment with an IAM instance profile.
    try:
        from utils.secrets import _load_from_aws
        # Clear cache to force a real AWS fetch attempt
        _cache.clear()
        _load_from_aws()
        
        if _cache:
            print(f"  ✓ SUCCESS: Loaded {len(_cache)} secrets from AWS Secrets Manager.")
            # Print keys found in AWS (but not values for safety)
            print(f"  Keys found in AWS: {list(_cache.keys())}")
        else:
            print("  ! AWS Secrets Manager was reached but returned no secrets.")
            print("    (Check if 'miipe/production' has any key-value pairs)")
            
    except Exception as e:
        print(f"  ! AWS Secrets Manager Fetch Attempt Finished.")
        print(f"    Reason for potential failure: {e}")
        print("    (This is expected if you are offline or have no AWS credentials configured)")

    # 4. Test Error Handling
    print("\n[4] Testing Error Handling...")
    try:
        get_secret("TOTALLY_RANDOM_KEY_THAT_DOES_NOT_EXIST")
        print("  ✗ Failed: Expected RuntimeError for missing key, but none was raised.")
    except RuntimeError as e:
        print(f"  ✓ Correctly raised RuntimeError: {e}")

    print("\n" + "="*50)
    print("TESTING COMPLETE")
    print("="*50 + "\n")

if __name__ == "__main__":
    test_secrets_manager()
