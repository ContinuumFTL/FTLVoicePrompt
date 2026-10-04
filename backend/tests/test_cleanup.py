from voice_prompt_sidecar.cleanup import clean_transcript


def test_clean_transcript_preserves_mixed_technical_terms():
    text = "  这个 React   component 里面的 useMemo 好像没必要，resource   merge 的逻辑可以抽出去。  "

    assert clean_transcript(text) == "这个 React component 里面的 useMemo 好像没必要，resource merge 的逻辑可以抽出去。"


def test_clean_transcript_removes_obvious_adjacent_duplicates():
    text = "帮我帮我 改一下这个页面 页面 的资源列表"

    assert clean_transcript(text) == "帮我 改一下这个页面 的资源列表"
