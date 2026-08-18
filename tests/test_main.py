from main import build_arg_parser


def test_default_args():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.once is False
    assert args.dry_run is False
    assert args.config == "config/config.yaml"
    assert args.targets == "config/targets.json"


def test_once_and_dry_run_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["--once", "--dry-run"])
    assert args.once is True
    assert args.dry_run is True
