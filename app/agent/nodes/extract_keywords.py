"""关键词抽取：jieba TF-IDF + 原句兜底。"""

import jieba.analyse
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.question import active_question
from app.agent.state import Nl2SqlState

ALLOW_POS = ("n", "nr", "ns", "nt", "nz", "v", "vn", "a", "an", "eng", "i", "l")


async def extract_keywords(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "抽取关键词", "status": "running"})
    question = active_question(state)
    words = jieba.analyse.extract_tags(question, allowPOS=ALLOW_POS)
    # dict.fromkeys(keys, value) = 用一组 key 造 dict，值全一样（默认 None）。
    # 用list取回 key 列表
    keywords = list(dict.fromkeys([*words, question])) # 每个元素都是一个关键字,除了最后一个
    runtime.stream_writer({"type": "progress", "step": "抽取关键词", "status": "success"})
    return {"keywords": keywords}
