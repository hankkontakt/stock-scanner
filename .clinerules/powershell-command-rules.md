
## Brief overview
These are critical rules for operating in a Windows PowerShell environment on the stock-scanner project. PowerShell does NOT support Unix-style `&&` and `||` command chaining, which requires special handling for all terminal commands.

## PowerShell command chaining (CRITICAL)
- **Never** use `&&` or `||` operators in terminal commands - they are not supported in PowerShell
- To chain commands sequentially (regardless of outcome), use a semicolon `;` (e.g., `cmd1; cmd2`)
- If the second command depends on the first succeeding, use PowerShell syntax: `cmd1; if ($?) { cmd2 }`
- Alternatively, split dependent commands into separate tool calls and execute them one at a time

## Command verification
- After every terminal command, explicitly wait for and read the output before proceeding
- Log whether the result was a Success, Failure, or Empty Output
- Never skip, assume, or hallucinate command results

## Strict retry limit
- Never execute the exact same command (or a highly similar command with the same intent) more than two (2) times in a row if it fails or produces the same unexpected result
- After two failures, halt autonomous execution and explain the issue to the user

## Anti-loop detection
- If reasoning or action steps start repeating (same check, same error, same fix), halt immediately
- Do not attempt to bypass issues autonomously after detecting a loop

## The escape hatch
- After a command fails twice, or if uncertain why a command skipped, stop and explain clearly to the user
- Ask for manual intervention or clarification
- Do not run any more commands until the user responds
