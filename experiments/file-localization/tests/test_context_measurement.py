"""Context-policy instrumentation counts replacement as well as deletion."""

from agent_eval.context import ToolResultElision

from file_localization.turn_loop_trial import _context_reduction


def test_elision_reports_reduced_payload_when_frame_count_is_unchanged() -> None:
    messages = [{"role": "user", "content": "task"}]
    for index in range(3):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": f"u{index}", "name": "read"}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"u{index}",
                            "content": "x" * 500,
                        }
                    ],
                },
            ]
        )

    prepared = ToolResultElision(keep_recent=1).prepare(
        messages, provider="anthropic", turn_idx=4
    )
    changed_frames, chars_elided = _context_reduction(messages, prepared)

    assert len(prepared) == len(messages)
    assert changed_frames == 2
    assert chars_elided > 800
