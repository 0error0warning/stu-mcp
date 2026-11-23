import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from stu_mcp.cli import main
from stu_mcp.clients import connect


def invoke(argv, monkeypatch, app, capsys):
    monkeypatch.setattr("stu_mcp.cli.App", lambda: app)
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_skill_reads_the_same_records_and_updates_only_local_status(app, monkeypatch, capsys):
    item = {"id": "notice-one", "source": "oa", "kind": "notice", "title": "测试通知",
            "body": "合成的通知正文", "url": "http://oa.stu.edu.cn/synthetic", "attachments": []}
    app.store.save_batch("oa", [item])
    code, result = invoke(["notice", "notice-one"], monkeypatch, app, capsys)
    assert code == 0
    assert result["item"]["body"] == "合成的通知正文"
    code, result = invoke(["attachment", "notice-one", "--index", "0"], monkeypatch, app, capsys)
    assert code == 1 and result["status"] == "no_attachments"
    code, result = invoke(["academic-summary"], monkeypatch, app, capsys)
    assert code == 1 and result["status"] == "needs_login"
    code, result = invoke(["profile", "--major", "合成专业"], monkeypatch, app, capsys)
    assert code == 0 and result["profile"]["major"] == "合成专业"
    code, result = invoke(["profile", "--interests", "竞赛"], monkeypatch, app, capsys)
    assert result["profile"] == {"major": "合成专业", "interests": "竞赛"}
    code, result = invoke(["task-status", "unknown-id", "done"], monkeypatch, app, capsys)
    assert code == 1 and result["status"] == "not_cached"
    task = {"id": "task-one", "kind": "task", "title": "合成待办", "school_status": "pending"}
    app.store.save_batch("local", [task])
    code, result = invoke(["task-status", "task-one", "done"], monkeypatch, app, capsys)
    assert code == 0 and result["status"] == "done"
    assert app.store.get("task-one")["school_status"] == "pending"
    assert app.store.list(sources=("local",))["items"][0]["status"] == "done"


@pytest.mark.parametrize("client", ["doubao-work", "generic-cli"])
def test_skill_preview_and_export_never_claim_native_mcp(app, tmp_path, client):
    preview = connect(client, app.runtime, home=tmp_path)
    assert preview["status"] == "preview"
    assert not Path(preview["artifact"]).exists()
    result = connect(client, app.runtime, home=tmp_path, apply=True)
    assert result["status"] == "skill_exported"
    assert result["verification"] == "local_execution_required"
    assert set(tmp_path.iterdir()) == {app.runtime.home}
    expected = {
        "stu-campus/SKILL.md", "stu-campus/runtime.json",
        "stu-campus/references/academics-and-card.md",
        "stu-campus/references/auth-and-ops.md",
        "stu-campus/references/checkin.md",
        "stu-campus/references/cli.md",
        "stu-campus/references/community-and-charging.md",
        "stu-campus/references/feedback.md",
        "stu-campus/references/medical-timetable.md",
        "stu-campus/references/notices.md",
        "stu-campus/references/repair-and-network.md",
        "stu-campus/references/takeout.md",
        "stu-campus/references/wechat-article.md",
    }
    with zipfile.ZipFile(result["artifact"]) as archive:
        assert set(archive.namelist()) == expected
        runtime = json.loads(archive.read("stu-campus/runtime.json"))
        assert Path(runtime["command"]).is_absolute()
        assert runtime["args"] == ["-m", "stu_mcp"]
        assert set(runtime) == {"command", "args"}
        assert "references/cli.md" in archive.read("stu-campus/SKILL.md").decode()
        cli_doc = archive.read("stu-campus/references/cli.md").decode()
        assert "academic-summary" in cli_doc
        assert "med_jw" in cli_doc
        assert "takeout" in cli_doc
    executed = subprocess.run([runtime["command"], *runtime["args"], "--version"],
                              env={**os.environ, "STU_MCP_HOME": str(app.runtime.home)},
                              capture_output=True, text=True, check=True, timeout=30)
    from stu_mcp import __version__
    assert executed.stdout.strip() == __version__
