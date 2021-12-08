def test_tn_simple_punct(tn_tokenizer):
    # We are well, how are you?
    text = "Re tsogile sentle, wêna o tsogile jang?"
    tokens = tn_tokenizer(text)
    assert tokens[0].idx == 0
    assert tokens[1].idx == 3
    assert tokens[2].idx == 11
    assert tokens[3].idx == 17
    assert tokens[4].idx == 19
    assert tokens[5].idx == 24
    assert tokens[6].idx == 26
    assert tokens[7].idx == 34
    assert tokens[8].idx == 38
