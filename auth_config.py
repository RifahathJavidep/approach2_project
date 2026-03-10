import os

def get_java_auth_headers():
    """
    Returns the standard headers required for all Java backend API calls.
    Includes the hardcoded development JWT token.
    """
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer katsu-hardcoded-jwt-token-for-development"
    }
