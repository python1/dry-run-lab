"""Install instructions name a real branch and warn before the starter command."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_skill_and_readme_get_the_code_from_main() -> None:
    skill = (ROOT / "bot" / "skills" / "getting-started" / "SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    instructions = (ROOT / "bot" / "instructions.md").read_text(encoding="utf-8")
    for text in (skill, readme, instructions):
        assert "stage-1" not in text
        assert "main" in text
    assert "git clone https://github.com/python1/dry-run-lab.git" in skill
    assert "archive/refs/heads/main.tar.gz" in skill
    assert "dryrun-lab unknown" in skill
    assert "dryrun-lab unknown" in readme
    fence = "```bash\n./ensure-running\n```"
    assert skill.index("OpenJDK 21") < skill.index(fence)
    assert skill.index("sudo") < skill.index(fence)
    assert readme.index("OpenJDK 21") < readme.index(fence)
    assert readme.index("sudo") < readme.index(fence)
    assert "25 deny ip" in readme
    assert "End with CNTL/Z." in skill
    assert "10.99.0.50" in skill
