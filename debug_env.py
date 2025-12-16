import os
from dotenv import load_dotenv
load_dotenv()

print(f"MODEL_NAME from os.environ: {os.environ.get('MODEL_NAME')}")
print(f"DB_HOST from os.environ: {os.environ.get('DB_HOST')}")

from config import settings
print(f"Settings MODEL_NAME: {settings.llm_model_name}")
