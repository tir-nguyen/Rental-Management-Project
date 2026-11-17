from dotenv import load_dotenv
import os

load_dotenv(".env", override=True)

import cloudinary
import cloudinary.uploader

config = cloudinary.config()

print("Cloud name:", bool(config.cloud_name))
print("API key:", bool(config.api_key))
print("API secret:", bool(config.api_secret))

try:
    result = cloudinary.uploader.upload(
        "https://res.cloudinary.com/demo/image/upload/sample.jpg",
        folder="rental-management/test",
        resource_type="image"
    )

    print("UPLOAD SUCCESS")
    print("Public ID:", result.get("public_id"))
    print("Secure URL exists:", bool(result.get("secure_url")))

except Exception as exc:
    print("UPLOAD FAILED")
    print("Error type:", type(exc).__name__)
    print("Error:", str(exc))
