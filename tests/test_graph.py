from models.graph import NodeType
from models.repository import Repository
from repository.graph_builder import GraphBuilder
from repository.graph_query import GraphQuery


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_graph_builder_creates_nodes_and_edges(db_session, sample_repo):
    repo = await _make_repo(db_session)
    builder = GraphBuilder(sample_repo, repo.id, db_session)
    graph = await builder.build_full_graph()
    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0


async def test_get_file_node_matches_full_relative_path(db_session, sample_repo):
    repo = await _make_repo(db_session)
    builder = GraphBuilder(sample_repo, repo.id, db_session)
    await builder.build_full_graph()

    query = GraphQuery(db_session, repo.id)
    main_node = await query.get_file_node("main.py")
    assert main_node is not None
    assert main_node.file_path == "main.py"


async def test_class_methods_are_contained_by_class_not_file(db_session, sample_repo):
    repo = await _make_repo(db_session)
    builder = GraphBuilder(sample_repo, repo.id, db_session)
    await builder.build_full_graph()

    query = GraphQuery(db_session, repo.id)
    widget = await query.get_symbol("Widget", NodeType.CLASS)
    assert widget is not None
    methods = await query.get_contained_symbols(widget.id)
    assert {"__init__", "render"} == {m.name for m in methods}


async def test_import_dependency_resolves_to_target_file(db_session, sample_repo):
    repo = await _make_repo(db_session)
    builder = GraphBuilder(sample_repo, repo.id, db_session)
    await builder.build_full_graph()

    query = GraphQuery(db_session, repo.id)
    main_node = await query.get_file_node("main.py")
    deps = await query.get_dependencies(main_node.id)
    assert "sample.py" in {d.name for d in deps}
