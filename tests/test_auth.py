"""Tests for JWT authentication."""

from src.api.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    register_user,
    authenticate_user,
    _users,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("testpassword123")
        assert hashed != "testpassword123"
        assert verify_password("testpassword123", hashed)

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)

    def test_hash_contains_salt(self):
        hashed = hash_password("test")
        assert "$" in hashed

    def test_different_salts_different_hashes(self):
        h1 = hash_password("same", "salt1")
        h2 = hash_password("same", "salt2")
        assert h1 != h2


class TestJWT:
    def test_create_and_decode_token(self):
        token = create_access_token({"sub": "test@example.com", "role": "analyst"})
        assert isinstance(token, str)
        payload = decode_token(token)
        assert payload["sub"] == "test@example.com"
        assert payload["role"] == "analyst"
        assert "exp" in payload

    def test_invalid_token_rejected(self):
        try:
            decode_token("invalid.token.value")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_tampered_token_rejected(self):
        token = create_access_token({"sub": "user@test.com"})
        # Tamper with token
        parts = token.split(".")
        parts[2] = "tampered"
        tampered = ".".join(parts)
        try:
            decode_token(tampered)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestUserRegistration:
    def setup_method(self):
        _users.clear()

    def test_register_and_authenticate(self):
        register_user("alice@firm.com", "securepass", "Alice", "strategist")
        user = authenticate_user("alice@firm.com", "securepass")
        assert user is not None
        assert user["name"] == "Alice"
        assert user["role"] == "strategist"

    def test_wrong_credentials(self):
        register_user("bob@firm.com", "pass123", "Bob", "analyst")
        assert authenticate_user("bob@firm.com", "wrongpass") is None
        assert authenticate_user("nobody@firm.com", "pass123") is None

    def test_duplicate_registration(self):
        register_user("carol@firm.com", "pass", "Carol", "coordinator")
        try:
            register_user("carol@firm.com", "pass2", "Carol2", "analyst")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
