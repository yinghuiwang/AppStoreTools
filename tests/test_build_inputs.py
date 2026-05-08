from asc.commands.build_inputs import BuildInputsCLI, ResolvedInputs


def test_build_inputs_cli_defaults_to_none():
    cli = BuildInputsCLI()
    assert cli.project is None
    assert cli.scheme is None
    assert cli.signing is None
    assert cli.profile is None
    assert cli.certificate is None
    assert cli.destination is None


def test_resolved_inputs_required_fields():
    r = ResolvedInputs(
        project_path="/tmp/x.xcodeproj",
        project_kind="project",
        scheme="MyApp",
        bundle_id="com.example.app",
        signing="auto",
        certificate=None,
        profile=None,
        destination="appstore",
    )
    assert r.scheme == "MyApp"
    assert r.certificate is None
