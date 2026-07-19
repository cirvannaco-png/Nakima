from models.repository import Repository
from neis.analyzers.project_modeler import ProjectModeler


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_snapshot_counts_languages_and_loc(db_session, sample_repo):
    repo = await _make_repo(db_session)
    snapshot = await ProjectModeler(db_session).build_snapshot(sample_repo, repo.id)

    assert snapshot.languages["python"] == 2  # sample.py, main.py
    assert snapshot.loc_by_language["python"] > 0
    assert snapshot.file_count == 2
    assert snapshot.repository_id == repo.id


async def test_snapshot_detects_test_files(db_session, sample_repo):
    (sample_repo / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    repo = await _make_repo(db_session)

    snapshot = await ProjectModeler(db_session).build_snapshot(sample_repo, repo.id)
    assert snapshot.test_file_count == 1
    assert snapshot.file_count == 3


async def test_snapshot_parses_requirements_txt_with_versions(db_session, sample_repo):
    (sample_repo / "requirements.txt").write_text(
        "fastapi==0.115.0\nrequests>=2.0\n# comment\n\nuvicorn[standard]==0.30.6\n"
    )
    repo = await _make_repo(db_session)

    snapshot = await ProjectModeler(db_session).build_snapshot(sample_repo, repo.id)
    names_and_versions = {(d["name"], d["version"]) for d in snapshot.dependencies}

    # requests>=2.0 (not ==) is intentionally not captured — only exact pins
    # are meaningful for tech_scout's "how far behind" comparison.
    assert ("fastapi", "0.115.0") in names_and_versions
    assert ("uvicorn", "0.30.6") in names_and_versions  # extras stripped from the name
    assert all(d["ecosystem"] == "pypi" for d in snapshot.dependencies)


async def test_snapshot_parses_package_json(db_session, sample_repo):
    (sample_repo / "package.json").write_text(
        '{"dependencies": {"react": "^18.2.0"}, "devDependencies": {"vite": "~5.0.0"}}'
    )
    repo = await _make_repo(db_session)

    snapshot = await ProjectModeler(db_session).build_snapshot(sample_repo, repo.id)
    deps = {(d["name"], d["version"], d["ecosystem"]) for d in snapshot.dependencies}
    assert ("react", "18.2.0", "npm") in deps  # ^ stripped
    assert ("vite", "5.0.0", "npm") in deps  # ~ stripped


async def test_snapshot_ignores_vendored_and_vcs_directories(db_session, sample_repo):
    (sample_repo / "node_modules").mkdir()
    (sample_repo / "node_modules" / "junk.js").write_text("var x = 1;")
    (sample_repo / ".git").mkdir()
    (sample_repo / ".git" / "config").write_text("[core]")
    repo = await _make_repo(db_session)

    snapshot = await ProjectModeler(db_session).build_snapshot(sample_repo, repo.id)
    assert snapshot.file_count == 2  # only sample.py and main.py — vendored/VCS dirs excluded


async def test_snapshot_is_null_health_score_for_non_python_repo(db_session, tmp_path):
    (tmp_path / "app.js").write_text("console.log('hi');\n")
    repo = await _make_repo(db_session)

    snapshot = await ProjectModeler(db_session).build_snapshot(tmp_path, repo.id)
    assert snapshot.health_score is None  # HealthScorer only runs when python files exist
