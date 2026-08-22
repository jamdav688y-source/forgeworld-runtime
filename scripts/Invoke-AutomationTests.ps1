# Thin, tokenizable entry point so Publish-VerifiedPullRequest.ps1's generic
# TestCommands runner (built around simple "pytest <path> -v" invocations)
# can also exercise this automation's own Pester suite with a real,
# propagated exit code -- without using Invoke-Pester's -EnableExit, which
# would terminate the calling PowerShell session instead of just this one.
$result = Invoke-Pester -Script "$PSScriptRoot\Publish-VerifiedPullRequest.Tests.ps1" -PassThru
Write-Output "$($result.PassedCount) passed, $($result.FailedCount) failed, $($result.SkippedCount) skipped"
exit $result.FailedCount
