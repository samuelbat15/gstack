from __future__ import annotations

import gmail_client


class FakeExecutable:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeMessagesResource:
    def __init__(self, list_response, get_responses=None):
        self.list_response = list_response
        self.get_responses = get_responses or {}
        self.list_calls = []
        self.get_calls = []

    def list(self, userId, maxResults=None, q=None):
        self.list_calls.append({"userId": userId, "maxResults": maxResults, "q": q})
        return FakeExecutable(self.list_response)

    def get(self, userId, id, format=None, metadataHeaders=None):
        self.get_calls.append({"userId": userId, "id": id})
        return FakeExecutable(self.get_responses[id])


class FakeUsersResource:
    def __init__(self, messages_resource):
        self._messages_resource = messages_resource

    def messages(self):
        return self._messages_resource


class FakeService:
    def __init__(self, messages_resource):
        self._users_resource = FakeUsersResource(messages_resource)

    def users(self):
        return self._users_resource


def make_message(from_="Sam <sam@example.com>", subject="Salut", snippet="petit texte"):
    return {
        "snippet": snippet,
        "payload": {"headers": [{"name": "From", "value": from_}, {"name": "Subject", "value": subject}]},
    }


class TestListRecentEmails:
    def test_returns_summaries_for_each_message(self, monkeypatch):
        messages = FakeMessagesResource(
            list_response={"messages": [{"id": "1"}, {"id": "2"}]},
            get_responses={
                "1": make_message(subject="Premier"),
                "2": make_message(subject="Deuxieme"),
            },
        )
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))

        result = gmail_client.list_recent_emails(max_results=2)

        assert result == [
            {"from": "Sam <sam@example.com>", "subject": "Premier", "snippet": "petit texte"},
            {"from": "Sam <sam@example.com>", "subject": "Deuxieme", "snippet": "petit texte"},
        ]
        assert messages.list_calls == [{"userId": "me", "maxResults": 2, "q": None}]

    def test_no_messages_returns_empty_list(self, monkeypatch):
        messages = FakeMessagesResource(list_response={"messages": []})
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))
        assert gmail_client.list_recent_emails() == []

    def test_missing_messages_key_returns_empty_list(self, monkeypatch):
        messages = FakeMessagesResource(list_response={})
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))
        assert gmail_client.list_recent_emails() == []


class TestSearchEmails:
    def test_passes_query_through_to_list_call(self, monkeypatch):
        messages = FakeMessagesResource(
            list_response={"messages": [{"id": "1"}]},
            get_responses={"1": make_message()},
        )
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))

        gmail_client.search_emails("from:sam", max_results=3)

        assert messages.list_calls == [{"userId": "me", "maxResults": 3, "q": "from:sam"}]


class TestExtractHeader:
    def test_case_insensitive_match(self):
        headers = [{"name": "subject", "value": "Bonjour"}]
        assert gmail_client._extract_header(headers, "Subject") == "Bonjour"

    def test_missing_header_returns_empty_string(self):
        assert gmail_client._extract_header([], "Subject") == ""


class TestDescribeRecentEmails:
    def test_formats_summaries_as_text(self, monkeypatch):
        messages = FakeMessagesResource(
            list_response={"messages": [{"id": "1"}]},
            get_responses={"1": make_message(from_="Sam", subject="Salut", snippet="ca va ?")},
        )
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))

        result = gmail_client.describe_recent_emails()

        assert result == "- Sam: Salut (ca va ?)"

    def test_no_emails_returns_placeholder(self, monkeypatch):
        messages = FakeMessagesResource(list_response={"messages": []})
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))
        assert gmail_client.describe_recent_emails() == "Aucun email trouve."

    def test_service_error_returns_error_string(self, monkeypatch):
        def raise_error():
            raise RuntimeError("credentials.json introuvable")

        monkeypatch.setattr("gmail_client._get_service", raise_error)
        result = gmail_client.describe_recent_emails()
        assert result.startswith("gmail: ")
        assert "credentials.json introuvable" in result


class TestDescribeEmailSearch:
    def test_formats_search_results(self, monkeypatch):
        messages = FakeMessagesResource(
            list_response={"messages": [{"id": "1"}]},
            get_responses={"1": make_message(from_="Sam", subject="RDV", snippet="demain 15h")},
        )
        monkeypatch.setattr("gmail_client._get_service", lambda: FakeService(messages))

        result = gmail_client.describe_email_search("rdv")

        assert result == "- Sam: RDV (demain 15h)"

    def test_service_error_returns_error_string(self, monkeypatch):
        def raise_error():
            raise RuntimeError("token expire")

        monkeypatch.setattr("gmail_client._get_service", raise_error)
        result = gmail_client.describe_email_search("rdv")
        assert result.startswith("gmail: ")
