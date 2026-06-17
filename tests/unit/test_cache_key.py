from src.core.security import generate_cache_key, hash_password, verify_password


def test_hash_password():
    password = "testpassword123"
    hashed = hash_password(password)
    
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrongpassword", hashed)


def test_generate_cache_key():
    key1 = generate_cache_key(
        document_id="doc1",
        query_text="What is this?",
        chunking_strategy_id="recursive",
        embedding_model="test-model",
    )
    
    key2 = generate_cache_key(
        document_id="doc1",
        query_text="What is this?",
        chunking_strategy_id="recursive",
        embedding_model="test-model",
    )
    
    assert key1 == key2
    assert len(key1) == 64


def test_cache_key_different_inputs():
    key1 = generate_cache_key(
        document_id="doc1",
        query_text="What is this?",
        chunking_strategy_id="recursive",
        embedding_model="test-model",
    )
    
    key2 = generate_cache_key(
        document_id="doc1",
        query_text="What is that?",
        chunking_strategy_id="recursive",
        embedding_model="test-model",
    )
    
    assert key1 != key2


def test_cache_key_case_insensitive():
    key1 = generate_cache_key(
        document_id="doc1",
        query_text="What is this?",
        chunking_strategy_id="recursive",
        embedding_model="test-model",
    )
    
    key2 = generate_cache_key(
        document_id="doc1",
        query_text="WHAT IS THIS?",
        chunking_strategy_id="recursive",
        embedding_model="test-model",
    )
    
    assert key1 == key2
