import os
from dotenv import load_dotenv
load_dotenv()
OPENAI_API_KEY=os.getenv('OPENAI_API_KEY','')
DEFAULT_TRANSLATION_MODEL=os.getenv('DEFAULT_TRANSLATION_MODEL','gpt-5.5')
DEFAULT_REVIEW_MODEL=os.getenv('DEFAULT_REVIEW_MODEL','gpt-5.5')
AVAILABLE_MODELS=['gpt-5.5','gpt-5.4-mini','gpt-5.4-nano']
