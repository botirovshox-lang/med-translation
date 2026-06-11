from rapidfuzz import fuzz
from db import get_all_tm,exact_tm_match
def find_tm_suggestion(source,min_score=82):
    e=exact_tm_match(source)
    if e: return {'score':100,'target_text':e['target_text'],'source_text':e['source_text'],'type':'exact'}
    best=None
    for row in get_all_tm():
        score=fuzz.token_sort_ratio(source,row['source_text'])
        if score>=min_score and (best is None or score>best['score']): best={'score':score,'target_text':row['target_text'],'source_text':row['source_text'],'type':'fuzzy'}
    return best
