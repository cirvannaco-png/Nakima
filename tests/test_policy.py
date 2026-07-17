from models.policy import RepositoryPolicy
from models.repository import Repository
from security.policy_checker import PolicyChecker


async def _make_repo_with_policy(db_session, **policy_kwargs):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    policy = RepositoryPolicy(repository_id=repo.id, **policy_kwargs)
    db_session.add(policy)
    await db_session.commit()
    return repo


async def test_check_branch_name_against_pattern(db_session):
    repo = await _make_repo_with_policy(db_session, branch_pattern=r"^nakima/.*")
    checker = PolicyChecker(db_session, repo.id)
    assert await checker.check_branch_name("nakima/issue-1") is True
    assert await checker.check_branch_name("feature/whatever") is False


async def test_check_required_reviewers_does_not_raise_nameerror(db_session):
    # This previously crashed with NameError: `policy` referenced before assignment.
    repo = await _make_repo_with_policy(db_session, required_reviewers=["alice", "bob"])
    checker = PolicyChecker(db_session, repo.id)
    assert await checker.check_required_reviewers({"requested_reviewers": [{"login": "alice"}]}) is False
    assert await checker.check_required_reviewers(
        {"requested_reviewers": [{"login": "alice"}, {"login": "bob"}]}
    ) is True


async def test_check_all_policies_does_not_raise_nameerror(db_session, sample_repo):
    # This previously crashed with NameError: `policy` referenced before assignment
    # in the branch-pattern violation message.
    repo = await _make_repo_with_policy(
        db_session, branch_pattern=r"^nakima/.*", required_reviewers=["alice"],
        require_docstrings=True, require_license=True,
    )
    checker = PolicyChecker(db_session, repo.id)
    violations = await checker.check_all_policies({
        "branch": "bad-branch", "pr_data": {"requested_reviewers": []},
        "repo_dir": str(sample_repo), "files": ["sample.py"],
    })
    assert any("Branch name" in v for v in violations)
    assert any("reviewers" in v for v in violations)
    assert any("docstring" in v.lower() for v in violations)
    assert any("LICENSE" in v for v in violations)


async def test_no_policy_means_no_violations(db_session, sample_repo):
    repo = Repository(full_name="kelson/no-policy-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    checker = PolicyChecker(db_session, repo.id)
    violations = await checker.check_all_policies({"branch": "anything", "repo_dir": str(sample_repo), "files": []})
    assert violations == []
