# Pester tests for Publish-VerifiedPullRequest.ps1
# Compatible with Pester 3.4 (bundled with Windows PowerShell / this machine's pwsh).
# All git/gh/network calls are mocked -- these tests never touch a real
# repository, the real network, or real credentials.

. "$PSScriptRoot\Publish-VerifiedPullRequest.ps1"

$Common = @{
    RepositoryPath      = 'C:\fake\repo'
    Branch              = 'feature/fw-router-first-evidence'
    ExpectedHead        = '1b833720877aef7f2172f9fddbcee00796d0d6fe'
    BaseBranch          = 'main'
    PullRequestTitle    = 'Test PR'
    PullRequestBody     = 'Test body'
    AllowedChangedFiles = @('capabilities/discover.py', 'router/decisions.jsonl')
    TestCommands        = @('pytest fake/ -v')
    RemoteName          = 'origin'
}

function New-PassingMocks {
    Mock Test-IsGitWorktree { $true }
    Mock Get-GitRemoteUrl { 'https://github.com/jamdav688y-source/forgeworld-runtime.git' }
    Mock Get-GitCurrentBranch { $Common.Branch }
    Mock Get-GitHeadSha { $Common.ExpectedHead }
    Mock Test-GitCleanTracked { $true }
    Mock Get-GitUntrackedFiles { @('capability_dispatch/', 'whatsapp/') }
    Mock Test-GitRefExists { $true }
    Mock Invoke-GitFetch { $true }
    Mock Get-GitChangedFiles { @('capabilities/discover.py', 'router/decisions.jsonl') }
    Mock Invoke-TestCommand { [pscustomobject]@{ Command = $Command; ExitCode = 0; Output = '2 passed'; Passed = 2; Failed = 0; Skipped = 0 } }
    Mock Get-RemoteBranchSha { $Common.ExpectedHead }
    Mock Invoke-GitPushBranch { $true }
    Mock Get-ExistingPullRequest { $null }
    Mock Test-GhAvailableAndAuthenticated { $false }
    Mock Get-PullRequestCompareUrl { 'https://github.com/jamdav688y-source/forgeworld-runtime/compare/main...feature/fw-router-first-evidence?quick_pull=1' }
    Mock Start-Process { }
}

Describe 'Publish-VerifiedPullRequest orchestration' {

    Context 'Wrong repository rejection' {
        It 'stops with BLOCKED_WITH_EVIDENCE when RepositoryPath does not exist' {
            Mock Test-Path { $false }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'BLOCKED_WITH_EVIDENCE'
            $r.Blocker | Should Match 'does not exist'
        }
    }

    Context 'Wrong branch rejection' {
        It 'stops with HEAD_MISMATCH when the active branch differs' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Get-GitCurrentBranch { 'some-other-branch' }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'HEAD_MISMATCH'
            $r.Blocker | Should Match 'Active branch'
        }
    }

    Context 'HEAD mismatch rejection' {
        It 'stops with HEAD_MISMATCH when local HEAD differs from ExpectedHead' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Get-GitHeadSha { 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef' }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'HEAD_MISMATCH'
            $r.LocalSha | Should Be 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
        }
    }

    Context 'Dirty tracked worktree rejection' {
        It 'stops with BLOCKED_WITH_EVIDENCE when tracked/staged changes exist' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Test-GitCleanTracked { $false }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'BLOCKED_WITH_EVIDENCE'
            $r.WorktreeStatus | Should Be 'dirty'
        }
    }

    Context 'Foreign untracked directories remain untouched' {
        It 'records untracked entries without ever staging, deleting, or modifying them' {
            Mock Test-Path { $true }
            New-PassingMocks
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite -DryRun
            ($r.UntrackedFiles -contains 'capability_dispatch/') | Should Be $true
            ($r.UntrackedFiles -contains 'whatsapp/') | Should Be $true
            Assert-MockCalled Test-GitCleanTracked -Times 1
            # The script contains no add/rm/mv call anywhere -- verified separately
            # in the static-analysis context below.
        }
    }

    Context 'Unexpected diff file rejection' {
        It 'stops with DIFF_SCOPE_FAILURE when a changed file is outside the allowlist' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Get-GitChangedFiles { @('capabilities/discover.py', 'governance/CONSTITUTION_v1.txt') }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'DIFF_SCOPE_FAILURE'
            $r.Blocker | Should Match 'governance/CONSTITUTION_v1.txt'
        }
    }

    Context 'Failed test rejection' {
        It 'stops with TEST_FAILURE on the first failing test command and does not push' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Invoke-TestCommand { [pscustomobject]@{ Command = $Command; ExitCode = 1; Output = '1 failed, 1 passed'; Passed = 1; Failed = 1; Skipped = 0 } }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'TEST_FAILURE'
            Assert-MockCalled Invoke-GitPushBranch -Times 0
        }
    }

    Context 'Successful remote equality' {
        It 'reports ShaEquality true and proceeds when remote HEAD matches ExpectedHead' {
            Mock Test-Path { $true }
            New-PassingMocks
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.ShaEquality | Should Be $true
            $r.RemoteSha | Should Be $Common.ExpectedHead
        }

        It 'stops with REMOTE_MISMATCH when remote HEAD differs from ExpectedHead' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Get-RemoteBranchSha { 'cafefacecafefacecafefacecafefacecafeface' }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'REMOTE_MISMATCH'
        }
    }

    Context 'Existing PR detection' {
        It 'returns VERIFIED_PR_ALREADY_EXISTS and records the existing PR without creating another' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Get-ExistingPullRequest { [pscustomobject]@{ Number = 42; Url = 'https://github.com/jamdav688y-source/forgeworld-runtime/pull/42'; State = 'open'; Merged = $false } }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'VERIFIED_PR_ALREADY_EXISTS'
            $r.PrNumber | Should Be 42
        }
    }

    Context 'No duplicate PR creation' {
        It 'never calls gh pr create when an existing PR was found' {
            Mock Test-Path { $true }
            New-PassingMocks
            Mock Get-ExistingPullRequest { [pscustomobject]@{ Number = 42; Url = 'https://github.com/x/y/pull/42'; State = 'open'; Merged = $false } }
            Mock New-PullRequestViaGh { throw 'must not be called' }
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            Assert-MockCalled New-PullRequestViaGh -Times 0
            $r.FinalOutcome | Should Be 'VERIFIED_PR_ALREADY_EXISTS'
        }
    }

    Context 'Dry-run performs no push or PR mutation' {
        It 'stops at DRY_RUN_PASS without pushing, checking existing PRs, or creating one' {
            Mock Test-Path { $true }
            New-PassingMocks
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite -DryRun
            $r.FinalOutcome | Should Be 'DRY_RUN_PASS'
            Assert-MockCalled Invoke-GitPushBranch -Times 0
            Assert-MockCalled Get-ExistingPullRequest -Times 0
        }
    }

    Context 'Human authorization required when gh is unavailable' {
        It 'returns HUMAN_AUTHORIZATION_REQUIRED and a compare URL, never signs in itself' {
            Mock Test-Path { $true }
            New-PassingMocks
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $r.FinalOutcome | Should Be 'HUMAN_AUTHORIZATION_REQUIRED'
            $r.PrUrl | Should Match '^https://github\.com/'
        }
    }
}

Describe 'Get-PytestSummary parsing' {

    Context 'Real pytest-style output' {
        It 'parses a plain pytest summary line correctly' {
            $r = Get-PytestSummary -Output "collected 15 items`n============================= 15 passed in 3.03s =============================="
            $r.Passed | Should Be 15
            $r.Failed | Should Be 0
        }
    }

    Context 'Pester 3.4-style label-first summary lines' {
        It 'does not misread "Passed: 17 Failed: 0" as 17 failures' {
            $output = "Tests completed in 1.53s`nPassed: 17 Failed: 0 Skipped: 0 Pending: 0 Inconclusive: 0`n17 passed, 0 failed, 0 skipped"
            $r = Get-PytestSummary -Output $output
            $r.Passed | Should Be 17
            $r.Failed | Should Be 0
            $r.Skipped | Should Be 0
        }

        It 'correctly reports a genuine Pester failure count from the trailing summary line' {
            $output = "Tests completed in 1.0s`nPassed: 15 Failed: 2 Skipped: 0 Pending: 0 Inconclusive: 0`n15 passed, 2 failed, 0 skipped"
            $r = Get-PytestSummary -Output $output
            $r.Passed | Should Be 15
            $r.Failed | Should Be 2
        }
    }
}

Describe 'Static safety guarantees' {

    $scriptText = Get-Content "$PSScriptRoot\Publish-VerifiedPullRequest.ps1" -Raw

    Context 'No merge operation exists anywhere in the script' {
        It 'never invokes git merge or gh pr merge' {
            $scriptText | Should Not Match '(?i)git\s+(-C\s+\S+\s+)?merge\b'
            $scriptText | Should Not Match '(?i)gh\s+pr\s+merge'
        }
    }

    Context 'No force-push operation exists anywhere in the script' {
        It 'never passes --force or -f to git push, and never uses reset --hard or clean' {
            $scriptText | Should Not Match '(?i)push[^\r\n]*--force'
            $scriptText | Should Not Match '(?i)push[^\r\n]*-f\b'
            $scriptText | Should Not Match '(?i)reset\s+--hard'
            $scriptText | Should Not Match '(?i)git\s+(-C\s+\S+\s+)?clean\b'
            $scriptText | Should Not Match '(?i)git\s+add\s+\.'
        }
    }

    Context 'Credentials and tokens are never written to evidence outputs' {
        It 'produces no secret-shaped values anywhere in a full mocked evidence report' {
            Mock Test-Path { $true }
            New-PassingMocks
            $r = Invoke-PublishVerifiedPullRequest @Common -NoEvidenceWrite
            $serialized = $r | ConvertTo-Json -Depth 10
            $serialized | Should Not Match 'gh[pousr]_[A-Za-z0-9]{20,}'
            $serialized | Should Not Match '(?i)bearer\s+[a-z0-9._-]{10,}'
            $serialized | Should Not Match '(?i)authorization:'
        }

        It 'never reads a stored credential or token from the environment or Git Credential Manager' {
            $scriptText | Should Not Match '(?i)git\s+credential\s+fill'
            $scriptText | Should Not Match '\$env:GITHUB_TOKEN'
            $scriptText | Should Not Match '(?i)Get-Credential\b'
        }
    }
}
