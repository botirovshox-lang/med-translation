from openai import OpenAI
from config import OPENAI_API_KEY
client=OpenAI(api_key=OPENAI_API_KEY)
def call_text(model,prompt):
    r=client.responses.create(model=model,input=prompt)
    return r.output_text
def call_json(model,prompt,schema_model):
    r=client.responses.parse(model=model,input=prompt,text_format=schema_model)
    return r.output_parsed.model_dump()
