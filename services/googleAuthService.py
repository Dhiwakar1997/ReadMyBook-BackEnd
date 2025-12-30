"""
Google OAuth ID Token Verification Service

This service handles secure verification of Google ID tokens received from client applications.
It validates token signature, expiration, audience, and required claims.
"""

import os
from google.oauth2 import id_token
from google.auth.transport import requests
from fastapi import HTTPException
from typing import Dict, Any


class GoogleAuthService:
    """Service for verifying Google ID tokens and extracting user information."""
    
    def __init__(self):
        """
        Initialize the Google Auth Service.
        
        Requires GOOGLE_WEB_CLIENT_ID environment variable to be set.
        This is the OAuth 2.0 client ID (Web application type) from Google Cloud Console.
        """
        self.client_id = os.getenv("GOOGLE_WEB_CLIENT_ID")
        if not self.client_id:
            raise ValueError(
                "GOOGLE_WEB_CLIENT_ID environment variable is required. "
                "Please set it in your .env file."
            )
        self.request_session = requests.Request()
    
    def verify_id_token(self, id_token_string: str) -> Dict[str, Any]:
        """
        Verify a Google ID token and extract user information.
        
        This method performs comprehensive validation:
        1. Verifies token signature using Google's public keys
        2. Validates token expiration
        3. Validates audience (aud) matches GOOGLE_WEB_CLIENT_ID
        4. Validates email_verified claim is true
        5. Extracts and returns user information
        
        Args:
            id_token_string: The Google ID token string to verify
            
        Returns:
            Dictionary containing verified user information:
            - sub: Google user ID
            - email: User's email address
            - name: User's full name
            - email_verified: Boolean indicating email verification status
            - Additional claims from the token
            
        Raises:
            HTTPException:
                - 401 if token is invalid, expired, or has wrong audience
                - 403 if email is not verified
        """
        try:
            # Verify the token using Google's verification service
            # This automatically validates:
            # - Token signature using Google's public keys
            # - Token expiration
            # - Token issuer
            id_info = id_token.verify_oauth2_token(
                id_token_string,
                self.request_session,
                self.client_id
            )
            
            # Additional validation: Ensure email is verified
            if not id_info.get("email_verified", False):
                raise HTTPException(
                    status_code=403,
                    detail="Email address not verified by Google"
                )
            
            # Extract required fields
            google_sub = id_info.get("sub")
            email = id_info.get("email")
            name = id_info.get("name", "")
            
            # Validate required fields are present
            if not google_sub:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token: missing 'sub' claim"
                )
            
            if not email:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token: missing 'email' claim"
                )
            
            return {
                "sub": google_sub,
                "email": email,
                "name": name,
                "email_verified": id_info.get("email_verified", False),
                "picture": id_info.get("picture"),  # Optional profile picture URL
                "given_name": id_info.get("given_name"),  # First name
                "family_name": id_info.get("family_name"),  # Last name
            }
            
        except HTTPException:
            # Re-raise HTTPExceptions (they already have proper status codes)
            raise
        except ValueError as e:
            # Token verification failed (invalid signature, expired, wrong audience, etc.)
            raise HTTPException(
                status_code=401,
                detail=f"Invalid Google ID token: {str(e)}"
            )
        except Exception as e:
            # Unexpected error during token verification
            raise HTTPException(
                status_code=500,
                detail=f"Error verifying Google ID token: {str(e)}"
            )

