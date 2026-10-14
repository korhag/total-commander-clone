#Requires -Version 5.1
<#
.SYNOPSIS
  Push and/or pull the Sorting Line repository, with interactive Git setup when needed.

.DESCRIPTION
  - Push: stages all changes, commits if needed, pushes to remote
  - Pull: fetches and merges from remote
  - If Git is not installed, the repo is not initialized, identity/remote are missing,
    or authentication fails, the script prompts for URL, username, PAT, etc.

.PARAMETER Action
  Push, Pull, or Both (default: Both).

.PARAMETER RemoteName
  Remote name (default: origin)

.PARAMETER Branch
  Branch to use (default: current branch, or main)

.EXAMPLE
  .\scripts\git-sync.ps1 -Action Push
  .\scripts\git-sync.ps1 -Action Pull
  .\scripts\git-sync.ps1
#>

[CmdletBinding()]
param(
    [ValidateSet("Push", "Pull", "Both")]
    [string] $Action = "Both",

    [string] $RemoteName = "origin",

    [string] $Branch = "",

    # Pull only: skip menu and match remote exactly (discard local changes).
    [switch] $PullMatchRemote
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Repository root = parent of scripts/
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$script:GitAccountRepoRoot = $RepoRoot
. (Join-Path $PSScriptRoot "git-account.ps1")

$script:GitAuth = $null  # @{ Username; Pat }
$script:GitSyncVersion = "4"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-WarnMsg([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Assert-GitInstalled {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw @"
Git is not installed or not on PATH.
Install Git for Windows: https://git-scm.com/download/win
Then reopen your terminal and run this script again.
"@
    }
    Write-Ok "Git found: $(git --version)"
}

function Format-GitArgsForDisplay {
    param([string[]] $Args)
    $safe = [System.Collections.Generic.List[string]]::new()
    $i = 0
    while ($i -lt $Args.Count) {
        if ($Args[$i] -eq "-c" -and ($i + 1) -lt $Args.Count -and $Args[$i + 1] -match '^http\.extraHeader=') {
            $safe.Add("-c")
            $safe.Add("http.extraHeader=***REDACTED***")
            $i += 2
            continue
        }
        $safe.Add($Args[$i])
        $i++
    }
    return ($safe.ToArray() -join " ")
}

function Test-GitHubWorkflowScopeError {
    param([string] $Output)
    return (
        ($Output -match 'workflow.*scope') -or
        ($Output -match 'refusing to allow a Personal Access Token.*workflow')
    )
}

function Test-GitHubAuthError {
    param([string] $Output)
    return (
        ($Output -match 'Authentication failed') -or
        ($Output -match 'Invalid username or password') -or
        ($Output -match 'Repository not found') -or
        ($Output -match '403') -or
        ($Output -match '401') -or
        (Test-GitHubWorkflowScopeError -Output $Output)
    )
}

function Test-GitHubNonFastForward {
    param([string] $Output)
    return (
        ($Output -match 'fetch first') -or
        ($Output -match '\[rejected\]') -or
        ($Output -match 'non-fast-forward')
    )
}

function Write-GitHubWorkflowScopeHelp {
    Write-Host @"

GitHub rejected the push: your PAT cannot update workflow files.

This repo includes .github/workflows/ci.yml.

Fine-grained PAT (chickline-v4): enable a SEPARATE permission:
  Repository permissions -> Workflows -> Read and write
  (Actions read/write alone is NOT enough for .github/workflows/*.yml)

Also keep: Contents read/write (code) on the same repository.

After changing permissions you MUST regenerate the token and paste the NEW token
(option 4 in this menu). Editing permissions alone does not upgrade an old token.

Classic PAT alternative: enable scopes 'repo' + 'workflow'.

"@ -ForegroundColor Yellow
}

function Clear-GitAuth {
    $script:GitAuth = $null
}

function Format-ProjectVersion {
    param([version] $Ver)
    if ($Ver.Revision -ge 0) {
        return ("{0}.{1}.{2}.{3}" -f $Ver.Major, $Ver.Minor, $Ver.Build, $Ver.Revision)
    }
    return ("{0}.{1}.{2}" -f $Ver.Major, $Ver.Minor, $Ver.Build)
}

function Read-CredentialFixChoice {
    Write-Host ""
    Write-Host "Update settings and retry push?" -ForegroundColor Cyan
    Write-Host "  [1] Retry with same username / URL / PAT"
    Write-Host "  [2] Change Git username"
    Write-Host "  [3] Change remote URL ($RemoteName)"
    Write-Host "  [4] Change Personal Access Token (PAT)"
    Write-Host "  [Q] Quit (cancel push)"
    $choice = (Read-Host "Choice").Trim().ToUpperInvariant()
    switch ($choice) {
        "1" { return "retry" }
        "2" { return "username" }
        "3" { return "url" }
        "4" { return "pat" }
        "Q" { return "quit" }
        default {
            Write-WarnMsg "Invalid choice. Enter 1, 2, 3, 4, or Q."
            return Read-CredentialFixChoice
        }
    }
}

function Update-GitUsername {
    $current = ""
    if ($script:GitAuth) { $current = $script:GitAuth.Username }
    $username = Read-HostWithDefault -Prompt "Git username" -Default $current
    if ($script:GitAuth) {
        $script:GitAuth.Username = $username
    } else {
        $pat = Read-SecurePat -Prompt "Personal Access Token (PAT) [input hidden]"
        $script:GitAuth = @{ Username = $username; Pat = $pat }
    }
    Write-Ok "Username updated"
}

function Update-GitPat {
    if (-not $script:GitAuth) {
        Get-AuthCredentials | Out-Null
        return
    }
    $pat = Read-SecurePat -Prompt "New Personal Access Token (PAT) [input hidden]"
    if ([string]::IsNullOrWhiteSpace($pat)) {
        throw "PAT cannot be empty."
    }
    $script:GitAuth.Pat = $pat
    Write-Ok "PAT updated (username unchanged: $($script:GitAuth.Username))"
}

function Update-RemoteUrlInteractive {
    $current = Get-RemoteUrl -Name $RemoteName
    $default = if ($current) { $current } else { "" }
    $inputUrl = Read-HostWithDefault -Prompt "Remote repository URL" -Default $default
    $url = Normalize-RemoteUrl -Url $inputUrl
    Invoke-Git -Args @("remote", "set-url", $RemoteName, $url) | Out-Null
    Write-Ok "Remote '$RemoteName' set to $url"
    return $url
}

function Convert-GitOutput {
    param([object] $Raw)
    $lines = @()
    foreach ($item in @($Raw)) {
        if ($null -eq $item) { continue }
        if ($item -is [System.Management.Automation.ErrorRecord]) {
            $lines += $item.ToString()
        } else {
            $lines += $item.ToString()
        }
    }
    return ($lines -join "`n").Trim()
}

function Invoke-Git {
    param([Parameter(Mandatory)][string[]] $Args)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = & git @Args 2>&1
        $exit = $LASTEXITCODE
        $text = Convert-GitOutput -Raw $raw
        if ($exit -ne 0) {
            $cmd = Format-GitArgsForDisplay $Args
            throw "git $cmd failed (exit $exit):`n$text"
        }
        if ($text) { return $text }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Test-GitRepository {
    try {
        Invoke-Git -Args @("rev-parse", "--git-dir") | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Initialize-GitRepository {
    Write-Step "Initializing Git repository"
    Invoke-Git -Args @("init") | Out-Null
    Write-Ok "Repository initialized at $RepoRoot"
}

function Read-HostWithDefault {
    param([string] $Prompt, [string] $Default = "")
    if ($Default) {
        $value = Read-Host "$Prompt [$Default]"
        if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
        return $value
    }
    do {
        $value = Read-Host $Prompt
    } while ([string]::IsNullOrWhiteSpace($value))
    return $value
}

function Read-SecurePat {
    param([string] $Prompt = "Personal Access Token (PAT)")
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Get-GitConfigValue {
    param([string] $Key)
    try {
        $v = Invoke-Git -Args @("config", "--get", $Key)
        return ($v | Select-Object -First 1).ToString().Trim()
    } catch {
        return $null
    }
}

function Ensure-GitIdentity {
    $name = Get-GitConfigValue -Key "user.name"
    $email = Get-GitConfigValue -Key "user.email"

    if (-not $name -or -not $email) {
        Write-Step "Git user identity is not configured"
        Write-WarnMsg "Commits need a name and email. These are stored locally for this repo only."
        if (-not $name) {
            $name = Read-HostWithDefault -Prompt "Your name (for commits)"
            Invoke-Git -Args @("config", "--local", "user.name", $name) | Out-Null
        }
        if (-not $email) {
            $email = Read-HostWithDefault -Prompt "Your email (for commits)"
            Invoke-Git -Args @("config", "--local", "user.email", $email) | Out-Null
        }
        Write-Ok ('Identity set: {0} <{1}>' -f $name, $email)
    } else {
        Write-Ok ('Git identity: {0} <{1}>' -f $name, $email)
    }
}

function Get-RemoteUrl {
    param([string] $Name)
    try {
        $url = Invoke-Git -Args @("remote", "get-url", $Name)
        return ($url | Select-Object -First 1).ToString().Trim()
    } catch {
        return $null
    }
}

function Normalize-RemoteUrl {
    param([string] $Url)
    $Url = $Url.Trim()
    if ($Url -notmatch '^https?://') {
        # Allow github.com/org/repo shorthand
        if ($Url -match '^[\w\.\-]+/[\w\.\-]+/[\w\.\-]+') {
            $Url = "https://github.com/$Url"
        } else {
            $Url = "https://$Url"
        }
    }
    if ($Url -notmatch '\.git$') {
        $Url = "$Url.git"
    }
    return $Url
}

function Ensure-Remote {
    $url = Get-RemoteUrl -Name $RemoteName
    if ($url) {
        Write-Ok "Remote '$RemoteName': $url"
        return $url
    }

    Write-Step "No Git remote configured"
    Write-Host @"
Enter your repository URL. Examples:
  https://github.com/your-org/your-repo.git
  github.com/your-org/your-repo
"@ -ForegroundColor DarkGray

    $inputUrl = Read-HostWithDefault -Prompt "Remote repository URL"
    $url = Normalize-RemoteUrl -Url $inputUrl

    $exists = $false
    try {
        $null = Invoke-Git -Args @("remote") 2>$null
        $remotes = @(Invoke-Git -Args @("remote"))
        $exists = $remotes -contains $RemoteName
    } catch { }

    if ($exists) {
        Invoke-Git -Args @("remote", "set-url", $RemoteName, $url) | Out-Null
    } else {
        Invoke-Git -Args @("remote", "add", $RemoteName, $url) | Out-Null
    }

    Write-Ok "Remote '$RemoteName' set to $url"
    return $url
}

function Get-AuthCredentials {
    if ($script:GitAuth) { return $script:GitAuth }

    Write-Step "Git authentication required"
    Write-Host @"
Use your Git hosting username and a Personal Access Token (PAT), not your account password.
  GitHub: Settings -> Developer settings -> Personal access tokens
  Azure DevOps: User settings -> Personal access tokens
"@ -ForegroundColor DarkGray

    $username = Read-HostWithDefault -Prompt "Git username"
    $pat = Read-SecurePat -Prompt "Personal Access Token (PAT) [input hidden]"

    if ([string]::IsNullOrWhiteSpace($pat)) {
        throw "PAT cannot be empty."
    }

    $script:GitAuth = @{ Username = $username; Pat = $pat }
    return $script:GitAuth
}

function Get-AuthHeader {
    $auth = Get-AuthCredentials
    $pair = "{0}:{1}" -f $auth.Username, $auth.Pat
    $bytes = [Text.Encoding]::ASCII.GetBytes($pair)
    $encoded = [Convert]::ToBase64String($bytes)
    return "AUTHORIZATION: basic $encoded"
}

function Invoke-GitWithAuth {
    param([Parameter(Mandatory)][string[]] $Args)
    $header = Get-AuthHeader
    $extra = @("-c", "http.extraHeader=$header")
    Invoke-Git -Args ($extra + $Args)
}

function Get-DefaultBranchName {
    $cfg = Get-GitConfigValue -Key "init.defaultBranch"
    if ($cfg) { return $cfg }
    return "main"
}

function Get-CurrentBranch {
    if ($Branch) { return $Branch }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = git branch --show-current 2>&1
        $name = (Convert-GitOutput -Raw $raw) -split "`n" | Select-Object -First 1
        $name = $name.Trim()
        if ($name) { return $name }
    } catch { } finally {
        $ErrorActionPreference = $prevEap
    }
    return Get-DefaultBranchName
}

function Ensure-BranchExists {
    param([string] $Name)
    $current = Get-CurrentBranch
    if ($current -eq $Name) {
        Write-Ok "Already on branch '$Name'"
        return
    }
    $listText = Invoke-Git -Args @("branch", "--list")
    $branches = @(
        if ($listText) {
            $listText -split "`n" | ForEach-Object { $_.Trim().TrimStart("* ") } | Where-Object { $_ }
        }
    )
    if ($branches -contains $Name) {
        $msg = Invoke-Git -Args @("checkout", $Name)
        if ($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }
        Write-Ok "Switched to branch '$Name'"
    } else {
        $msg = Invoke-Git -Args @("checkout", "-b", $Name)
        if ($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }
        Write-Ok "Created and switched to branch '$Name'"
    }
}

function Test-NeedsCommit {
    $status = Invoke-Git -Args @("status", "--porcelain")
    return ($status | Measure-Object).Count -gt 0
}

function Get-ChangelogPath {
    Join-Path $RepoRoot "CHANGELOG.md"
}

function Get-ChangelogReleasedVersions {
    param([string] $ChangelogPath = (Get-ChangelogPath))
    if (-not (Test-Path $ChangelogPath)) {
        return @()
    }
    $content = Get-Content -Path $ChangelogPath -Raw
    $found = [regex]::Matches($content, '(?m)^## \[(\d+\.\d+\.\d+)\]')
    $list = [System.Collections.Generic.List[version]]::new()
    foreach ($m in $found) {
        $list.Add([version]$m.Groups[1].Value)
    }
    return @($list | Sort-Object -Unique)
}

function Test-ChangelogHasUnreleasedNotes {
    param([string] $ChangelogPath = (Get-ChangelogPath))
    if (-not (Test-Path $ChangelogPath)) {
        return $false
    }
    $lines = Get-Content -Path $ChangelogPath
    $inUnreleased = $false
    foreach ($line in $lines) {
        if ($line -match '^\s*## \[Unreleased\]') {
            $inUnreleased = $true
            continue
        }
        if ($inUnreleased -and $line -match '^\s*## \[') {
            break
        }
        if ($inUnreleased -and $line -match '^\s*-\s+\S') {
            return $true
        }
    }
    return $false
}

function Get-ChangelogLatestReleasedVersion {
    $versions = @(Get-ChangelogReleasedVersions)
    if ($versions.Count -eq 0) {
        return [version]"0.1.0"
    }
    # Ensure we return a single Version, not an array (nested-array bug guard).
    $latest = $versions | Sort-Object | Select-Object -Last 1
    if ($latest -is [array]) {
        return [version]$latest[0].ToString()
    }
    return $latest
}

function Get-SuggestedCommitVersion {
    $latest = Get-ChangelogLatestReleasedVersion
    if (Test-ChangelogHasUnreleasedNotes) {
        $major = $latest.Major
        $minor = $latest.Minor
        $build = $latest.Build + 1
        if ($build -gt 999) {
            $minor += 1
            $build = 0
        }
        return [version]"$major.$minor.$build"
    }
    return $latest
}

function Get-DefaultCommitMessage {
    param([string] $Summary = "Update")
    $ver = Get-SuggestedCommitVersion
    return ("v{0}: {1}" -f (Format-ProjectVersion $ver), $Summary)
}

function Ensure-InitialCommit {
    $hasCommits = $true
    try {
        Invoke-Git -Args @("rev-parse", "HEAD") | Out-Null
    } catch {
        $hasCommits = $false
    }

    if (-not $hasCommits) {
        Write-Step "Creating initial commit"
        $msg = Get-DefaultCommitMessage -Summary "Initial commit"
        Write-Ok "Suggested version from CHANGELOG.md: v$(Format-ProjectVersion (Get-SuggestedCommitVersion))"
        Invoke-Git -Args @("add", "-A") | Out-Null
        Invoke-Git -Args @("commit", "-m", $msg) | Out-Null
        Write-Ok "Initial commit created"
        return
    }

    if (Test-NeedsCommit) {
        Write-Step "Uncommitted changes detected"
        $suggestedVer = Get-SuggestedCommitVersion
        $latestReleased = Get-ChangelogLatestReleasedVersion
        if (Test-ChangelogHasUnreleasedNotes) {
            Write-Ok ("CHANGELOG [Unreleased] has notes - suggesting next patch: v{0} (latest release: v{1})" -f (Format-ProjectVersion $suggestedVer), (Format-ProjectVersion $latestReleased))
        } else {
            Write-Ok ("CHANGELOG latest release: v{0} (no [Unreleased] notes - using that version)" -f (Format-ProjectVersion $latestReleased))
        }
        $defaultMsg = Get-DefaultCommitMessage
        $msg = Read-HostWithDefault -Prompt "Commit message" -Default $defaultMsg
        Invoke-Git -Args @("add", "-A") | Out-Null
        Invoke-Git -Args @("commit", "-m", $msg) | Out-Null
        Write-Ok "Changes committed"
    }
}

function Invoke-GitPush {
    param(
        [string] $RemoteUrl
    )

    Write-Step "Pushing to Git ($RemoteName)"
    $branch = Get-CurrentBranch
    Ensure-BranchExists -Name $branch
    Ensure-InitialCommit

    $pushArgs = @("push", "-u", $RemoteName, $branch)
    $useAuth = [bool]$script:GitAuth

    while ($true) {
        try {
            if ($useAuth) {
                Invoke-GitWithAuth -Args $pushArgs | ForEach-Object { Write-Host $_ }
            } else {
                Invoke-Git -Args $pushArgs | ForEach-Object { Write-Host $_ }
            }
            Write-Ok "Push completed ($RemoteName / $branch)"
            return
        } catch {
            $err = $_.Exception.Message

            if (-not $useAuth) {
                Write-WarnMsg "Push failed; retrying with username + PAT..."
                $useAuth = $true
                continue
            }

            if (Test-GitHubNonFastForward $err) {
                switch (Read-PushRejectedChoice) {
                    "pull" {
                        $b = Get-CurrentBranch
                        $null = Ensure-UpstreamBranch -Remote $RemoteName -Branch $b
                        Invoke-GitPullMatchRemote -Remote $RemoteName -Branch $b
                        Write-WarnMsg "Pull done. Run git-push again if you still need to upload from this PC."
                        return
                    }
                    "force" {
                        Write-WarnMsg "Force pushing (overwrites remote branch)..."
                        $forceArgs = @("push", "-u", "--force", $RemoteName, $branch)
                        Invoke-GitWithAuth -Args $forceArgs | ForEach-Object { Write-Host $_ }
                        Write-Ok "Force push completed ($RemoteName / $branch)"
                        return
                    }
                    "quit" { throw "Push cancelled." }
                }
            }

            Write-Host "`nPush failed." -ForegroundColor Red
            if (Test-GitHubWorkflowScopeError $err) {
                Write-GitHubWorkflowScopeHelp
            } else {
                Write-Host $err -ForegroundColor DarkGray
            }

            if (-not (Test-GitHubAuthError $err)) {
                throw
            }

            switch (Read-CredentialFixChoice) {
                "retry" { continue }
                "username" {
                    Update-GitUsername
                    continue
                }
                "url" {
                    $RemoteUrl = Update-RemoteUrlInteractive
                    continue
                }
                "pat" {
                    Clear-GitAuth
                    continue
                }
                "quit" {
                    throw "Push cancelled."
                }
            }
        }
    }
}

function Test-HasUpstream {
    try {
        Invoke-Git -Args @("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-RemoteBranchExists {
    param([string] $Remote, [string] $Branch)
    $lsArgs = @("ls-remote", "--heads", $Remote, "refs/heads/$Branch")

    function Test-LsRemote {
        param([bool] $UseAuth)
        try {
            if ($UseAuth) {
                if (-not $script:GitAuth) { return $false }
                $refs = Invoke-GitWithAuth -Args $lsArgs
            } else {
                $refs = Invoke-Git -Args $lsArgs
            }
            return -not [string]::IsNullOrWhiteSpace($refs)
        } catch {
            return $false
        }
    }

    if (Test-LsRemote $false) { return $true }
    if ($script:GitAuth) { return (Test-LsRemote $true) }
    return $false
}

function Ensure-UpstreamBranch {
    param([string] $Remote, [string] $Branch)
    if (Test-HasUpstream) { return $true }

    if (Test-RemoteBranchExists -Remote $Remote -Branch $Branch) {
        Write-WarnMsg "Local branch is not tracking ${Remote}/${Branch}; linking and continuing..."
        Invoke-Git -Args @("branch", "--set-upstream-to=${Remote}/${Branch}", $Branch) | Out-Null
        Write-Ok "Now tracking ${Remote}/${Branch}"
        return $true
    }

    Write-WarnMsg @"
No upstream branch configured and ${Remote}/${Branch} does not exist on the remote yet.

On the computer that has your latest work, run: scripts\git-push.cmd
Or clone fresh: git clone https://github.com/korhag/faceswap-on-rust.git
"@
    return $false
}

function Invoke-GitRemoteCommand {
    param([Parameter(Mandatory)][string[]] $Args)
    if ($script:GitAuth) {
        try {
            $out = Invoke-GitWithAuth -Args $Args
            if ($out) { $out | ForEach-Object { Write-Host $_ } }
            return
        } catch {
            Write-WarnMsg "Authenticated request failed; retrying without PAT header..."
        }
    }
    $out = Invoke-Git -Args $Args
    if ($out) { $out | ForEach-Object { Write-Host $_ } }
}

function Read-PushRejectedChoice {
    Write-Host ""
    Write-Host "GitHub already has commits you do not have locally." -ForegroundColor Yellow
    Write-Host "On this computer you usually want to download GitHub, not upload." -ForegroundColor DarkGray
    Write-Host "  [1] Pull from GitHub first (match remote exactly - default)" -ForegroundColor Cyan
    Write-Host "  [2] Force push - overwrite GitHub with this copy (destructive)"
    Write-Host "  [Q] Cancel"
    $choice = (Read-Host "Choice [1]").Trim().ToUpperInvariant()
    switch ($choice) {
        "" { return "pull" }
        "1" { return "pull" }
        "2" { return "force" }
        "Q" { return "quit" }
        default {
            Write-WarnMsg "Invalid choice. Enter 1, 2, or Q."
            return Read-PushRejectedChoice
        }
    }
}

function Read-PullModeChoice {
    Write-Host ""
    Write-Host "How do you want to pull?" -ForegroundColor Cyan
    Write-Host "  [1] Match GitHub exactly - discard local commits, edits, and untracked files (default)"
    Write-Host "  [2] Normal pull - merge; keep local commits and changes when possible"
    Write-Host "  [Q] Cancel"
    $choice = (Read-Host "Choice [1]").Trim().ToUpperInvariant()
    switch ($choice) {
        "" { return "remote" }
        "1" { return "remote" }
        "2" { return "merge" }
        "Q" { return "cancel" }
        default {
            Write-WarnMsg "Invalid choice. Enter 1, 2, or Q."
            return Read-PullModeChoice
        }
    }
}

function Invoke-GitPullMatchRemote {
    param([string] $Remote, [string] $Branch)
    $remoteRef = "${Remote}/${Branch}"
    Write-Ok "Fetching $remoteRef ..."
    Invoke-GitRemoteCommand -Args @("fetch", $Remote, $Branch)
    Write-WarnMsg "Resetting local branch to $remoteRef (all local changes will be lost)..."
    Invoke-Git -Args @("reset", "--hard", $remoteRef) | Out-Null
    Invoke-Git -Args @("clean", "-fd") | ForEach-Object { if ($_) { Write-Host "    $_" } }
    Write-Ok "Local copy now matches $remoteRef"
}

function Invoke-GitPullMerge {
    param([string] $Remote, [string] $Branch)
    $pullArgs = @("pull", $Remote, $Branch)
    Invoke-GitRemoteCommand -Args $pullArgs
    Write-Ok "Pull completed ($Remote / $Branch)"
}

function Invoke-GitPull {
    Write-Step "Pulling from Git ($RemoteName)"
    $branch = Get-CurrentBranch
    Ensure-BranchExists -Name $branch

    if (-not (Ensure-UpstreamBranch -Remote $RemoteName -Branch $branch)) {
        if (-not $script:GitAuth) {
            Write-WarnMsg "Save a PAT with scripts\git-config-account.cmd - plain 'git pull' cannot access private repos."
            return
        }
        Write-WarnMsg "Could not detect remote branch; trying fetch with saved PAT anyway..."
        try {
            Invoke-GitRemoteCommand -Args @("fetch", $RemoteName, $branch)
            Invoke-Git -Args @("branch", "--set-upstream-to=${RemoteName}/${branch}", $branch) | Out-Null
            Write-Ok "Linked to ${RemoteName}/${branch}"
        } catch {
            Write-WarnMsg "Fetch failed. Create the repo on GitHub or fix the remote URL."
            return
        }
    }

    $mode = if ($PullMatchRemote) { "remote" } else { Read-PullModeChoice }
    switch ($mode) {
        "remote" { Invoke-GitPullMatchRemote -Remote $RemoteName -Branch $branch }
        "merge" { Invoke-GitPullMerge -Remote $RemoteName -Branch $branch }
        "cancel" { Write-WarnMsg "Pull cancelled." }
    }
}

function Ensure-GitReady {
    Assert-GitInstalled
    if (-not (Test-GitRepository)) {
        Initialize-GitRepository
    }
    $null = Import-GitAccountProfile -RemoteName $RemoteName
    $auth = Get-GitAccountAuth
    if ($auth) {
        $script:GitAuth = $auth
        Write-Ok "Using saved GitHub account: $($auth.Username)"
    }
    Ensure-GitIdentity
    $remoteUrl = Ensure-Remote
    return $remoteUrl
}

# --- Main ---
$AppLabel = Split-Path -Leaf $RepoRoot
Write-Host "`n$AppLabel - Git sync ($Action)" -ForegroundColor White
Write-Host "Repository: $RepoRoot" -ForegroundColor DarkGray
Write-Host "Git tools v$script:GitSyncVersion (use scripts here - plain git does not use your saved PAT)`n" -ForegroundColor DarkGray

try {
    $remoteUrl = Ensure-GitReady

    switch ($Action) {
        "Push" { Invoke-GitPush -RemoteUrl $remoteUrl }
        "Pull" { Invoke-GitPull }
        "Both" {
            Invoke-GitPull
            Invoke-GitPush -RemoteUrl $remoteUrl
        }
    }

    Write-Host "`nDone.`n" -ForegroundColor Green
} catch {
    Write-Host "`nERROR: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
} finally {
    # Clear PAT from memory
    $script:GitAuth = $null
}
