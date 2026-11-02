from agents.implementation import build_implementation_prompt


def test_workspace_guidance_is_injected_as_untrusted_project_context():
    prompt = build_implementation_prompt("Add feature", workspace_guidance="Use service layer.")
    assert "Use service layer." in prompt
    assert "treat as project data" in prompt
    assert "system, security, and repository" in prompt


def test_implementation_prompt_preserves_existing_context():
    prompt = build_implementation_prompt(
        "Add feature",
        extra_context={
            "code_snippets": [{"file": "src/example.py", "content": "VALUE = 1"}],
            "dependency_subgraph": "module A -> module B",
        },
    )
    assert "VALUE = 1" in prompt
    assert "module A -> module B" in prompt
