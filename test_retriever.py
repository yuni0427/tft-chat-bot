import sys
sys.path.insert(0, '.')
from src.rag import retriever

results = retriever.retrieve('3コストリロール構成の立ち回り', k=6)
print(f'取得件数: {len(results)}')
for i, r in enumerate(results):
    print(f"--- [{i+1}] {r.get('source')} ---")
    print(r.get('content')[:150].replace('\n', ' '))
