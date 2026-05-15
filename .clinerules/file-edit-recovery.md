## File Edit Recovery Rules

These rules address the "User closed text editor" error that can occur when using `write_to_file`.

### Prevention

1. **Always use `write_to_file` with `absolutePath` + `content` parameters only.**
   - Do NOT use tools that open an interactive text editor
   - The `write_to_file` tool is stateless and writes directly - no editor interaction needed

2. **Keep file content self-contained in the `content` parameter.**
   - All content must be provided as a string in the `content` parameter
   - Never rely on a separate editor session to complete the write

3. **For large files (1000+ lines), segment writes.**
   - Write smaller sections separately rather than one massive write
   - This avoids timeouts and reduces risk of editor failures

### Recovery

If you encounter "Error executing write_to_file: User closed text editor":

1. **Do NOT retry the same `write_to_file` call** - it will likely fail again
2. Instead, use `replace_in_file` on the target file if it was partially written:
   - Check what was written (read the file)
   - Add the remaining content using SEARCH/REPLACE blocks
3. If the file doesn't exist at all:
   - Use `execute_command` with Python to write the file:
     ```
     python -c "open('path/to/file', 'w', encoding='utf-8').write('''content''')"
     ```
   - This bypasses the editor entirely and is more reliable
4. If that also fails, use PowerShell to write the file:
   ```
   $content = @'
   multiline content here
   '@
   Set-Content -Path "d:\Trader\stock-scanner\path\to\file" -Value $content -Encoding UTF8
   ```

### Verification

After any file write attempt (successful or recovered):
1. Read the file back to verify content is correct
2. If content is partial, use `replace_in_file` to add missing sections
3. Never assume a file write succeeded without verification
