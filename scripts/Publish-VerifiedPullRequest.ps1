#Requires -Version 7.0
<#
.SYNOPSIS
Verify a branch's evidence (clean tree, expected HEAD, in-scope diff, passing tests),
publish it, and open/create the corresponding pull request -- without ever merging,
force-pushing, or handling credentials itself.

.DESCRIPTION
Every gate below is a hard stop: on failure the script records FinalOutcome + Blocker
in the evidence report and returns without doing anything further. Interactive GitHub
authentication (Git Credential Manager, `gh auth login`) is never bypassed, extracted,
or simulated -- when it's required, the script reports HUMAN_AUTHORIZATION_REQUIRED and
stops, or lets the human-facing `git push` prompt surface naturally.
#>
[CmdletBinding()]
param(
    [string]$RepositoryPath = "C:\Users\jamda\OneDrive\Documents\forgeworld-runtime",
    [string]$Branch = "feature/fw-router-first-evidence",
    [string]$ExpectedHead = "1b833720877aef7f2172f9fddbcee00796d0d6fe",
    [string]$BaseBranch = "main",
    [string]$PullRequestTitle = "Record first routed evidence loop and correct executable discovery",
    [string]$PullRequestBody = @"
## Implemented and tested
- Recorded one real routing outcome and its post-outcome scoring effect.
- Added bounded Python executable launch, identity, and version verification.
- Rejected the inert Windows Store Python execution alias.
- Added the explicit ``VERSION_UNSUPPORTED`` evidence state.
- Passed 15 focused discovery tests.
- Passed 13 Mobile Research Companion regression tests.
- Preserved both operational ledgers byte-for-byte after the corrective increments.

## Not claimed
- ``evidence_level`` affects router scoring.
- The selected capability changed after recorded evidence.
- Every registered command is launch-verified.
- A model catalog or evaluation substrate exists.
- This branch is production-promoted.

## Known limitation
``mission_router.py`` consumes ``reachability_confidence`` but not ``evidence_level``.
Therefore ``PATH_FOUND`` and ``VERSION_VERIFIED`` can remain numerically equivalent in
routing calculations.
"@,
    [string[]]$AllowedChangedFiles = @(
        "capabilities/discover.py",
        "capabilities/history.jsonl",
        "capabilities/registry.json",
        "capabilities/tests/test_discover.py",
        "router/decisions.jsonl"
    ),
    [string[]]$TestCommands = @(
        "pytest capabilities/tests/test_discover.py -v",
        "pytest forgeworld-mobile-research/tests/ -v"
    ),
    [string]$RemoteName = "origin",
    [switch]$DryRun,
    [switch]$SkipPush,
    [switch]$OpenBrowserFallback
)

$script:ExpectedRemotePattern = 'jamdav688y-source/forgeworld-runtime'

# ---------------------------------------------------------------------------
# Low-level, individually mockable git/gh/API wrappers. Nothing above this
# line does I/O; everything below is a thin wrapper so orchestration logic
# can be unit-tested without touching a real repository or network.
# ---------------------------------------------------------------------------

function Test-IsGitWorktree {
    param([Parameter(Mandatory)][string]$RepoPath)
    $out = & git -C $RepoPath rev-parse --is-inside-work-tree 2>&1
    return ($LASTEXITCODE -eq 0 -and $out -match 'true')
}

function Get-GitRemoteUrl {
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$RemoteName)
    $out = & git -C $RepoPath remote get-url $RemoteName 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out.Trim()
}

function Get-GitCurrentBranch {
    param([Parameter(Mandatory)][string]$RepoPath)
    ( & git -C $RepoPath branch --show-current 2>&1 ).Trim()
}

function Get-GitHeadSha {
    param([Parameter(Mandatory)][string]$RepoPath)
    ( & git -C $RepoPath rev-parse HEAD 2>&1 ).Trim()
}

function Get-GitStatusPorcelain {
    param([Parameter(Mandatory)][string]$RepoPath)
    & git -C $RepoPath status --porcelain 2>&1
}

function Test-GitCleanTracked {
    <# True only if there are zero tracked/staged modifications. Untracked
       files ('??' lines) do not fail this check -- they are reported
       separately and never touched. #>
    param([Parameter(Mandatory)][string]$RepoPath)
    $lines = Get-GitStatusPorcelain -RepoPath $RepoPath
    $tracked = @($lines | Where-Object { $_ -and -not $_.StartsWith('??') })
    return ($tracked.Count -eq 0)
}

function Get-GitUntrackedFiles {
    param([Parameter(Mandatory)][string]$RepoPath)
    $lines = Get-GitStatusPorcelain -RepoPath $RepoPath
    @($lines | Where-Object { $_.StartsWith('??') } | ForEach-Object { $_.Substring(3).Trim() })
}

function Invoke-GitFetch {
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$RemoteName)
    & git -C $RepoPath fetch $RemoteName 2>&1 | Out-Null
    return $LASTEXITCODE -eq 0
}

function Test-GitRefExists {
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$Ref)
    & git -C $RepoPath rev-parse --verify --quiet $Ref 2>&1 | Out-Null
    return $LASTEXITCODE -eq 0
}

function Get-GitChangedFiles {
    <# Files changed on $Branch relative to $BaseBranch, base..branch style. #>
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$BaseBranch, [Parameter(Mandatory)][string]$Branch)
    $out = & git -C $RepoPath diff --name-only "$BaseBranch..$Branch" 2>&1
    if ($LASTEXITCODE -ne 0) { return @() }
    @($out | Where-Object { $_ })
}

function Get-RemoteBranchSha {
    <# Returns the remote branch's HEAD sha, or $null if the branch does not exist remotely. #>
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$RemoteName, [Parameter(Mandatory)][string]$Branch)
    $out = & git -C $RepoPath ls-remote $RemoteName "refs/heads/$Branch" 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
    (($out | Select-Object -First 1) -split '\s+')[0]
}

function Invoke-GitPushBranch {
    <# Runs a plain, non-force push. Any interactive credential prompt (Git
       Credential Manager / browser sign-in) is left entirely to the user --
       this function never supplies, reads, or bypasses credentials. #>
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$RemoteName, [Parameter(Mandatory)][string]$Branch)
    & git -C $RepoPath push -u $RemoteName $Branch 2>&1
    return $LASTEXITCODE -eq 0
}

function Get-PytestSummary {
    <# Parses a pytest console summary line into passed/failed/skipped totals. #>
    param([Parameter(Mandatory)][string]$Output)
    $passed = 0; $failed = 0; $skipped = 0
    if ($Output -match '(\d+)\s+passed') { $passed = [int]$Matches[1] }
    if ($Output -match '(\d+)\s+failed') { $failed = [int]$Matches[1] }
    if ($Output -match '(\d+)\s+skipped') { $skipped = [int]$Matches[1] }
    [pscustomobject]@{ Passed = $passed; Failed = $failed; Skipped = $skipped }
}

function Invoke-TestCommand {
    <# Runs one test command string (e.g. "pytest tests/ -v") from RepoPath.
       "pytest" is resolved through the Mobile Research Companion's own venv
       when present, since no global pytest is installed on this machine;
       otherwise it is invoked as a bare command on PATH. #>
    param([Parameter(Mandatory)][string]$RepoPath, [Parameter(Mandatory)][string]$Command)

    $tokens = $Command -split '\s+'
    $venvPytest = Join-Path $RepoPath 'forgeworld-mobile-research\.venv\Scripts\python.exe'
    $exe = $tokens[0]
    $rest = @($tokens[1..($tokens.Length - 1)])

    if ($exe -eq 'pytest' -and (Test-Path $venvPytest)) {
        $exe = $venvPytest
        $rest = @('-m', 'pytest') + $rest
    }

    Push-Location $RepoPath
    try {
        $output = & $exe @rest 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $summary = Get-PytestSummary -Output $output
    [pscustomobject]@{
        Command  = $Command
        ExitCode = $exitCode
        Output   = $output
        Passed   = $summary.Passed
        Failed   = $summary.Failed
        Skipped  = $summary.Skipped
    }
}

function Get-RepoOwnerAndName {
    param([Parameter(Mandatory)][string]$RemoteUrl)
    if ($RemoteUrl -match 'github\.com[:/]+([^/]+)/([^/.]+?)(\.git)?$') {
        return [pscustomobject]@{ Owner = $Matches[1]; Repo = $Matches[2] }
    }
    return $null
}

function Get-PullRequestCompareUrl {
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$BaseBranch,
        [Parameter(Mandatory)][string]$Branch,
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Body
    )
    $encTitle = [System.Net.WebUtility]::UrlEncode($Title)
    $encBody = [System.Net.WebUtility]::UrlEncode($Body)
    "https://github.com/$Owner/$Repo/compare/$BaseBranch...$Branch`?quick_pull=1&title=$encTitle&body=$encBody"
}

function Test-GhAvailableAndAuthenticated {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) { return $false }
    & gh auth status 2>&1 | Out-Null
    return $LASTEXITCODE -eq 0
}

function New-PullRequestViaGh {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$BaseBranch,
        [Parameter(Mandatory)][string]$Branch,
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Body
    )
    Push-Location $RepoPath
    try {
        $out = & gh pr create --title $Title --body $Body --base $BaseBranch --head $Branch --repo "$Owner/$Repo" 2>&1 | Out-String
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    $url = ($out -split "`n" | Where-Object { $_ -match '^https://github\.com/' } | Select-Object -First 1)
    if (-not $url) { return $null }
    $number = $null
    if ($url -match '/pull/(\d+)') { $number = [int]$Matches[1] }
    [pscustomobject]@{ Number = $number; Url = $url.Trim() }
}

function Get-ExistingPullRequest {
    <# Read-only, unauthenticated GitHub API check for an open PR with the
       given base/head. Public-repo reads require no token. #>
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$BaseBranch,
        [Parameter(Mandatory)][string]$Branch
    )
    $uri = "https://api.github.com/repos/$Owner/$Repo/pulls?state=open&base=$BaseBranch&head=$Owner`:$Branch"
    try {
        $prs = Invoke-RestMethod -Uri $uri -Headers @{ 'User-Agent' = 'forgeworld-publisher' } -ErrorAction Stop
    } catch {
        return $null
    }
    if ($prs -and $prs.Count -gt 0) {
        $pr = $prs[0]
        return [pscustomobject]@{
            Number = $pr.number
            Url    = $pr.html_url
            State  = $pr.state
            Merged = $false
        }
    }
    return $null
}

function Get-PullRequestState {
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][int]$Number
    )
    $uri = "https://api.github.com/repos/$Owner/$Repo/pulls/$Number"
    try {
        $pr = Invoke-RestMethod -Uri $uri -Headers @{ 'User-Agent' = 'forgeworld-publisher' } -ErrorAction Stop
    } catch {
        return $null
    }
    [pscustomobject]@{
        Number     = $pr.number
        Url        = $pr.html_url
        State      = $pr.state
        BaseBranch = $pr.base.ref
        HeadBranch = $pr.head.ref
        HeadSha    = $pr.head.sha
        Merged     = [bool]$pr.merged
    }
}

# ---------------------------------------------------------------------------
# Evidence report writer
# ---------------------------------------------------------------------------

function Write-EvidenceReport {
    param(
        [Parameter(Mandatory)][hashtable]$Evidence,
        [Parameter(Mandatory)][string]$RepoPath
    )
    $dir = Join-Path $RepoPath 'artifacts\pr-publication'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null

    $json = $Evidence | ConvertTo-Json -Depth 10
    $jsonPath = Join-Path $dir 'latest.json'
    $json | Set-Content -Path $jsonPath -Encoding utf8

    $md = @()
    $md += "# PR Publication Evidence"
    $md += ""
    $md += "- Timestamp: $($Evidence.Timestamp)"
    $md += "- Final outcome: **$($Evidence.FinalOutcome)**"
    if ($Evidence.Blocker) { $md += "- Blocker: $($Evidence.Blocker)" }
    $md += "- Repository: $($Evidence.RepositoryPath)"
    $md += "- Remote: $($Evidence.RemoteUrl)"
    $md += "- Base branch: $($Evidence.BaseBranch)"
    $md += "- Head branch: $($Evidence.HeadBranch)"
    $md += "- Expected SHA: $($Evidence.ExpectedSha)"
    $md += "- Local SHA: $($Evidence.LocalSha)"
    $md += "- Remote SHA: $($Evidence.RemoteSha)"
    $md += "- SHA equality: $($Evidence.ShaEquality)"
    $md += "- Worktree status: $($Evidence.WorktreeStatus)"
    $md += "- Allowlist result: $($Evidence.AllowlistResult)"
    if ($Evidence.TestTotals) {
        $md += "- Test totals: passed=$($Evidence.TestTotals.Passed) failed=$($Evidence.TestTotals.Failed) skipped=$($Evidence.TestTotals.Skipped)"
    }
    $md += "- Push result: $($Evidence.PushResult)"
    $md += "- Existing PR check: $($Evidence.ExistingPrCheck)"
    $md += "- PR creation method: $($Evidence.PrCreationMethod)"
    $md += "- PR number: $($Evidence.PrNumber)"
    $md += "- PR URL: $($Evidence.PrUrl)"
    $md += "- PR status: $($Evidence.PrStatus)"
    $md += "- Merged state: $($Evidence.PrMerged)"
    $mdPath = Join-Path $dir 'latest.md'
    ($md -join "`n") | Set-Content -Path $mdPath -Encoding utf8

    $historyDir = Join-Path $dir 'history'
    New-Item -ItemType Directory -Path $historyDir -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item -Path $jsonPath -Destination (Join-Path $historyDir "$stamp.json") -Force

    [pscustomobject]@{ JsonPath = $jsonPath; MarkdownPath = $mdPath }
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

function Invoke-PublishVerifiedPullRequest {
    param(
        [Parameter(Mandatory)][string]$RepositoryPath,
        [Parameter(Mandatory)][string]$Branch,
        [Parameter(Mandatory)][string]$ExpectedHead,
        [Parameter(Mandatory)][string]$BaseBranch,
        [Parameter(Mandatory)][string]$PullRequestTitle,
        [Parameter(Mandatory)][string]$PullRequestBody,
        [Parameter(Mandatory)][string[]]$AllowedChangedFiles,
        [Parameter(Mandatory)][string[]]$TestCommands,
        [string]$RemoteName = 'origin',
        [switch]$DryRun,
        [switch]$SkipPush,
        [switch]$OpenBrowserFallback,
        [switch]$NoEvidenceWrite
    )

    $evidence = [ordered]@{
        Timestamp           = (Get-Date).ToString('o')
        RepositoryPath      = $RepositoryPath
        RemoteUrl           = $null
        BaseBranch          = $BaseBranch
        HeadBranch          = $Branch
        ExpectedSha         = $ExpectedHead
        LocalSha            = $null
        RemoteSha           = $null
        ShaEquality         = $null
        WorktreeStatus      = $null
        UntrackedFiles      = @()
        ChangedFiles        = @()
        AllowlistResult     = $null
        TestCommands        = @()
        TestExitCodes       = @()
        TestTotals          = $null
        PushResult          = 'not_attempted'
        AuthBoundaryResult  = $null
        ExistingPrCheck     = $null
        PrCreationMethod    = $null
        PrNumber            = $null
        PrUrl               = $null
        PrStatus            = $null
        PrMerged            = $null
        FinalOutcome        = $null
        Blocker             = $null
    }

    function Stop-WithOutcome([string]$Outcome, [string]$Reason) {
        $evidence.FinalOutcome = $Outcome
        $evidence.Blocker = $Reason
        if (-not $NoEvidenceWrite) { Write-EvidenceReport -Evidence $evidence -RepoPath $RepositoryPath | Out-Null }
        return [pscustomobject]$evidence
    }

    # Gate 1: repository path exists
    if (-not (Test-Path $RepositoryPath)) {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' "RepositoryPath does not exist: $RepositoryPath"
    }

    # Gate 2: is a git worktree
    if (-not (Test-IsGitWorktree -RepoPath $RepositoryPath)) {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' "RepositoryPath is not a git worktree: $RepositoryPath"
    }

    # Gate 3: origin matches expected repository
    $remoteUrl = Get-GitRemoteUrl -RepoPath $RepositoryPath -RemoteName $RemoteName
    $evidence.RemoteUrl = $remoteUrl
    if (-not $remoteUrl -or $remoteUrl -notmatch [regex]::Escape($script:ExpectedRemotePattern)) {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' "Remote '$RemoteName' does not point to the expected repository ($script:ExpectedRemotePattern). Found: $remoteUrl"
    }

    # Gate 7: branch is not main (checked early -- never operate on main)
    if ($Branch -eq $BaseBranch -or $Branch -eq 'main') {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' "Branch must not be '$BaseBranch'/main."
    }

    # Gate 4: active branch matches requested branch
    $currentBranch = Get-GitCurrentBranch -RepoPath $RepositoryPath
    if ($currentBranch -ne $Branch) {
        return Stop-WithOutcome 'HEAD_MISMATCH' "Active branch '$currentBranch' does not match requested branch '$Branch'."
    }

    # Gate 5: local HEAD matches ExpectedHead
    $localSha = Get-GitHeadSha -RepoPath $RepositoryPath
    $evidence.LocalSha = $localSha
    if ($localSha -ne $ExpectedHead) {
        return Stop-WithOutcome 'HEAD_MISMATCH' "Local HEAD '$localSha' does not equal ExpectedHead '$ExpectedHead'."
    }

    # Gate 6: no tracked/staged modifications (untracked files reported, not blocked on)
    $clean = Test-GitCleanTracked -RepoPath $RepositoryPath
    $evidence.UntrackedFiles = @(Get-GitUntrackedFiles -RepoPath $RepositoryPath)
    $evidence.WorktreeStatus = if ($clean) { 'clean' } else { 'dirty' }
    if (-not $clean) {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' 'Tracked or staged modifications exist in the worktree.'
    }

    # Gate 8: base branch exists (locally or as a remote-tracking ref)
    if (-not (Test-GitRefExists -RepoPath $RepositoryPath -Ref $BaseBranch) -and
        -not (Test-GitRefExists -RepoPath $RepositoryPath -Ref "$RemoteName/$BaseBranch")) {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' "Base branch '$BaseBranch' does not exist locally or as $RemoteName/$BaseBranch."
    }

    # Fetch remote refs (read-only)
    Invoke-GitFetch -RepoPath $RepositoryPath -RemoteName $RemoteName | Out-Null

    # Enumerate changed files against BaseBranch
    $changed = @(Get-GitChangedFiles -RepoPath $RepositoryPath -BaseBranch $BaseBranch -Branch $Branch)
    $evidence.ChangedFiles = $changed

    # Gate 9: every changed file must be in AllowedChangedFiles
    $unexpected = @($changed | Where-Object { $AllowedChangedFiles -notcontains $_ })
    if ($unexpected.Count -gt 0) {
        $evidence.AllowlistResult = "fail: $($unexpected -join ', ')"
        return Stop-WithOutcome 'DIFF_SCOPE_FAILURE' "Unexpected file(s) outside AllowedChangedFiles: $($unexpected -join ', ')"
    }
    $evidence.AllowlistResult = 'pass'

    # Gate 10: every required test must pass; stop on first failure
    $testResults = @()
    foreach ($cmd in $TestCommands) {
        $result = Invoke-TestCommand -RepoPath $RepositoryPath -Command $cmd
        $testResults += $result
        $evidence.TestCommands += $cmd
        $evidence.TestExitCodes += $result.ExitCode
        if ($result.ExitCode -ne 0) {
            $evidence.TestTotals = [ordered]@{
                Passed  = ($testResults | Measure-Object -Property Passed -Sum).Sum
                Failed  = ($testResults | Measure-Object -Property Failed -Sum).Sum
                Skipped = ($testResults | Measure-Object -Property Skipped -Sum).Sum
            }
            return Stop-WithOutcome 'TEST_FAILURE' "Test command failed: $cmd (exit $($result.ExitCode))"
        }
    }
    $evidence.TestTotals = [ordered]@{
        Passed  = ($testResults | Measure-Object -Property Passed -Sum).Sum
        Failed  = ($testResults | Measure-Object -Property Failed -Sum).Sum
        Skipped = ($testResults | Measure-Object -Property Skipped -Sum).Sum
    }

    if ($DryRun) {
        return Stop-WithOutcome 'DRY_RUN_PASS' $null
    }

    # Gate 11 (push phase): check remote branch existence; push only if absent and not SkipPush
    $remoteSha = Get-RemoteBranchSha -RepoPath $RepositoryPath -RemoteName $RemoteName -Branch $Branch
    if (-not $remoteSha) {
        if ($SkipPush) {
            return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' 'Remote branch does not exist and SkipPush was set.'
        }
        $pushed = Invoke-GitPushBranch -RepoPath $RepositoryPath -RemoteName $RemoteName -Branch $Branch
        $evidence.PushResult = if ($pushed) { 'pushed' } else { 'push_failed' }
        if (-not $pushed) {
            return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' 'git push did not complete successfully (interactive authentication may still be pending).'
        }
        Invoke-GitFetch -RepoPath $RepositoryPath -RemoteName $RemoteName | Out-Null
        $remoteSha = Get-RemoteBranchSha -RepoPath $RepositoryPath -RemoteName $RemoteName -Branch $Branch
    } else {
        $evidence.PushResult = 'already_published'
    }

    $evidence.RemoteSha = $remoteSha
    $evidence.ShaEquality = ($remoteSha -eq $ExpectedHead)
    if (-not $evidence.ShaEquality) {
        return Stop-WithOutcome 'REMOTE_MISMATCH' "Remote HEAD '$remoteSha' does not equal ExpectedHead '$ExpectedHead'."
    }

    # PR phase
    $ownerRepo = Get-RepoOwnerAndName -RemoteUrl $remoteUrl
    if (-not $ownerRepo) {
        return Stop-WithOutcome 'BLOCKED_WITH_EVIDENCE' "Could not parse owner/repo from remote URL: $remoteUrl"
    }

    $existing = Get-ExistingPullRequest -Owner $ownerRepo.Owner -Repo $ownerRepo.Repo -BaseBranch $BaseBranch -Branch $Branch
    if ($existing) {
        $evidence.ExistingPrCheck = 'found'
        $evidence.PrCreationMethod = 'none_already_exists'
        $evidence.PrNumber = $existing.Number
        $evidence.PrUrl = $existing.Url
        $evidence.PrStatus = $existing.State
        $evidence.PrMerged = $existing.Merged
        return Stop-WithOutcome 'VERIFIED_PR_ALREADY_EXISTS' $null
    }
    $evidence.ExistingPrCheck = 'not_found'

    if (Test-GhAvailableAndAuthenticated) {
        $created = New-PullRequestViaGh -RepoPath $RepositoryPath -Owner $ownerRepo.Owner -Repo $ownerRepo.Repo `
            -BaseBranch $BaseBranch -Branch $Branch -Title $PullRequestTitle -Body $PullRequestBody
        if ($created) {
            $evidence.PrCreationMethod = 'gh_cli'
            $state = Get-PullRequestState -Owner $ownerRepo.Owner -Repo $ownerRepo.Repo -Number $created.Number
            $evidence.PrNumber = $created.Number
            $evidence.PrUrl = $created.Url
            if ($state) {
                $evidence.PrStatus = $state.State
                $evidence.PrMerged = $state.Merged
            }
            return Stop-WithOutcome 'VERIFIED_PR_CREATED' $null
        }
    }

    # No authenticated gh available: never install it automatically, never
    # sign in ourselves. Hand back a pre-filled URL instead.
    $compareUrl = Get-PullRequestCompareUrl -Owner $ownerRepo.Owner -Repo $ownerRepo.Repo `
        -BaseBranch $BaseBranch -Branch $Branch -Title $PullRequestTitle -Body $PullRequestBody
    $evidence.PrCreationMethod = 'browser_fallback_url'
    $evidence.PrUrl = $compareUrl
    $evidence.AuthBoundaryResult = 'HUMAN_AUTHORIZATION_REQUIRED_FOR_PR_CREATION'
    if ($OpenBrowserFallback) {
        Start-Process $compareUrl | Out-Null
    }
    return Stop-WithOutcome 'HUMAN_AUTHORIZATION_REQUIRED' $null
}

# ---------------------------------------------------------------------------
# Guarded entry point -- does nothing when dot-sourced (e.g. by tests)
# ---------------------------------------------------------------------------
if ($MyInvocation.InvocationName -ne '.') {
    $result = Invoke-PublishVerifiedPullRequest `
        -RepositoryPath $RepositoryPath -Branch $Branch -ExpectedHead $ExpectedHead `
        -BaseBranch $BaseBranch -PullRequestTitle $PullRequestTitle -PullRequestBody $PullRequestBody `
        -AllowedChangedFiles $AllowedChangedFiles -TestCommands $TestCommands -RemoteName $RemoteName `
        -DryRun:$DryRun -SkipPush:$SkipPush -OpenBrowserFallback:$OpenBrowserFallback
    $result | ConvertTo-Json -Depth 10
}
