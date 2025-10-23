#!/usr/bin/env python3
"""
Script to measure crash regression discovery metrics.

Metrics measured:
- How many crash regressions are found by release-mgmt-account-bot@mozilla.tld vs by humans
- Time between the regressing bug creation and when the regression bug is opened
- Resolution metrics for crash regressions found by bot vs humans
- Statistics for crash bugs that are not regressions
"""

from datetime import datetime
from bugbug import db, bugzilla


# Bot email for crash regression filing
CRASH_BOT_EMAIL = "release-mgmt-account-bot@mozilla.tld"

# Date range for analysis
OLDEST_BUG = "2025-01-01T00:00:00Z"


def parse_datetime(dt_str):
    """Parse Bugzilla datetime string to datetime object."""
    if not dt_str:
        return None
    # Handle both formats: with and without microseconds
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def is_other_bot_email(email: str) -> bool:
    """Check if the email is belong to a bot or component-watching account.

    Args:
        email: the account login email.
    """
    if email.endswith("@disabled.tld"):
        return False

    return email.endswith(".bugs") or email.endswith(".tld")


def is_crash_regression(bug):
    """
    Check if a bug is a crash regression.
    Returns True if bug has 'regression' keyword and has a crash signature.
    """
    keywords = bug.get("keywords", [])
    if "regression" not in keywords:
        return False

    crash_signature = bug.get("cf_crash_signature", "")
    return bool(crash_signature and crash_signature.strip())


def is_crash_bug(bug):
    """
    Check if a bug is a crash bug (regardless of regression status).
    Returns True if bug has a crash signature.
    """
    crash_signature = bug.get("cf_crash_signature", "")
    return bool(crash_signature and crash_signature.strip())


def is_filed_by_bugbot(bug):
    """Check if bug was filed by the crash bot."""
    return bug.get("creator", "") == CRASH_BOT_EMAIL


def get_patch_landing_time(bug):
    """
    Get the time when a patch landed (when bug was resolved as FIXED).
    Returns the datetime when the bug status changed to RESOLVED/VERIFIED/CLOSED with resolution FIXED.
    """

    if "history" in bug:
        for event in bug["history"]:
            for change in event["changes"]:
                # Look for status change to RESOLVED, VERIFIED, or CLOSED
                if change["field_name"] == "status" and change["added"] in (
                    "RESOLVED",
                    "VERIFIED",
                    "CLOSED",
                ):
                    return parse_datetime(event["when"])

    return None


def build_bug_cache(bugs):
    """
    Build a cache of bug_id -> bug data for quick lookups.
    Returns a dictionary mapping bug IDs to their data.
    """
    print("Building bug cache...")
    cache = {}
    count = 0
    for bug in bugs:
        cache[bug.get("id")] = {
            "creation_time": parse_datetime(bug.get("creation_time")),
            "patch_landing_time": get_patch_landing_time(bug),
            "status": bug.get("status", ""),
            "resolution": bug.get("resolution", ""),
        }
        count += 1
        if count % 10000 == 0:
            print(f"  Cached {count} bugs...")

    print(f"Bug cache built with {len(cache)} bugs")
    return cache


def analyze_crash_regression(bug, bug_cache):
    """
    Analyze a single crash regression bug.
    Returns a dict with analysis results or None if bug should be skipped.
    """
    creation_time = parse_datetime(bug.get("creation_time"))
    if not creation_time:
        return None

    # Filter by date
    oldest_bug_date = parse_datetime(OLDEST_BUG)
    if creation_time < oldest_bug_date:
        return None

    # Check if this is a crash regression
    if not is_crash_regression(bug):
        return None

    # Determine if filed by bot or human
    filed_by_bot = is_filed_by_bugbot(bug)

    # Skip bugs filed by other bots
    if not filed_by_bot and is_other_bot_email(bug.get("creator", "")):
        return None

    # Get regressed_by bugs
    regressed_by_ids = bug.get("regressed_by") or []

    # Calculate time to discovery
    # If multiple regressing bugs, use the most recent patch landing time
    regressing_bug_time = None
    if regressed_by_ids:
        for bug_id in regressed_by_ids:
            if bug_id in bug_cache:
                # Use patch landing time instead of creation time
                reg_time = bug_cache[bug_id]["patch_landing_time"]
                if reg_time:
                    if regressing_bug_time is None or reg_time > regressing_bug_time:
                        regressing_bug_time = reg_time

    minutes_to_discovery = None
    if regressing_bug_time:
        minutes_to_discovery = (
            creation_time - regressing_bug_time
        ).total_seconds() / 60

    # Check resolution status
    status = bug.get("status", "")
    resolution = bug.get("resolution", "")
    is_resolved = status in ("RESOLVED", "VERIFIED", "CLOSED")

    # Calculate time to resolution if resolved
    minutes_to_resolution = None
    if is_resolved:
        # Look for resolution time in history
        if "history" in bug:
            for event in bug["history"]:
                for change in event["changes"]:
                    if change["field_name"] == "status" and change["added"] in (
                        "RESOLVED",
                        "VERIFIED",
                        "CLOSED",
                    ):
                        resolution_time = parse_datetime(event["when"])
                        if resolution_time:
                            minutes_to_resolution = (
                                resolution_time - creation_time
                            ).total_seconds() / 60
                            break
                if minutes_to_resolution:
                    break

    return {
        "filed_by_bot": filed_by_bot,
        "minutes_to_discovery": minutes_to_discovery,
        "is_resolved": is_resolved,
        "minutes_to_resolution": minutes_to_resolution,
        "has_regressed_by": len(regressed_by_ids) > 0,
    }


def analyze_non_regression_crash(bug):
    """
    Analyze a single crash bug that is NOT a regression.
    Returns a dict with analysis results or None if bug should be skipped.
    """
    creation_time = parse_datetime(bug.get("creation_time"))
    if not creation_time:
        return None

    # Filter by date
    oldest_bug_date = parse_datetime(OLDEST_BUG)
    if creation_time < oldest_bug_date:
        return None

    # Check if this is a crash bug but NOT a regression
    if not is_crash_bug(bug):
        return None

    keywords = bug.get("keywords", [])
    if "regression" in keywords:
        return None  # This is a regression, skip it

    # Determine if filed by bot or human
    filed_by_bot = is_filed_by_bugbot(bug)

    # Skip bugs filed by other bots
    if not filed_by_bot and is_other_bot_email(bug.get("creator", "")):
        return None

    # Check resolution status
    status = bug.get("status", "")
    is_resolved = status in ("RESOLVED", "VERIFIED", "CLOSED")

    # Calculate time to resolution if resolved
    minutes_to_resolution = None
    if is_resolved:
        # Look for resolution time in history
        if "history" in bug:
            for event in bug["history"]:
                for change in event["changes"]:
                    if change["field_name"] == "status" and change["added"] in (
                        "RESOLVED",
                        "VERIFIED",
                        "CLOSED",
                    ):
                        resolution_time = parse_datetime(event["when"])
                        if resolution_time:
                            minutes_to_resolution = (
                                resolution_time - creation_time
                            ).total_seconds() / 60
                            break
                if minutes_to_resolution:
                    break

    return {
        "filed_by_bot": filed_by_bot,
        "is_resolved": is_resolved,
        "minutes_to_resolution": minutes_to_resolution,
    }


def print_report(metrics):
    """Print a comprehensive report of the metrics."""
    print("\n" + "=" * 80)
    print("CRASH REGRESSION DISCOVERY METRICS REPORT")
    print("=" * 80)
    print(f"Analysis period: From {OLDEST_BUG}")
    print("=" * 80)

    for category_name, category_data in [
        ("CRASH REGRESSIONS FOUND BY BOT (release-mgmt-account-bot)", "found_by_bot"),
        ("CRASH REGRESSIONS FOUND BY HUMANS", "found_by_humans"),
    ]:
        data = metrics[category_data]
        print(f"\n{category_name}")
        print("-" * 80)

        print(f"Total crash regressions discovered: {data['total']}")
        print(f"  - With regressed_by field: {data['with_regressed_by']}")
        print(f"  - Without regressed_by field: {data['without_regressed_by']}")

        print(f"\nResolution status:")
        print(f"  - Resolved: {data['resolved']}")
        print(f"  - Unresolved: {data['total'] - data['resolved']}")
        if data["total"] > 0:
            resolution_rate = (data["resolved"] / data["total"]) * 100
            print(f"  - Resolution rate: {resolution_rate:.1f}%")

        # Time to discovery statistics
        print("\n  Time to Discovery (from patch landing to regression report):")
        print("  " + "-" * 76)

        discovery_times = data["minutes_to_discovery"]
        if discovery_times:
            sorted_times = sorted(discovery_times)
            count = len(sorted_times)
            avg = sum(sorted_times) / count
            median = sorted_times[count // 2]
            p25 = sorted_times[int(count * 0.25)]
            p75 = sorted_times[int(count * 0.75)]
            p90 = sorted_times[int(count * 0.90)]

            print(f"    Count: {count}")
            print(
                f"    Average: {avg:.1f} minutes ({avg/60:.1f} hours, {avg/1440:.1f} days)"
            )
            print(
                f"    Median: {median:.1f} minutes ({median/60:.1f} hours, {median/1440:.1f} days)"
            )
            print(
                f"    25th percentile: {p25:.1f} minutes ({p25/60:.1f} hours, {p25/1440:.1f} days)"
            )
            print(
                f"    75th percentile: {p75:.1f} minutes ({p75/60:.1f} hours, {p75/1440:.1f} days)"
            )
            print(
                f"    90th percentile: {p90:.1f} minutes ({p90/60:.1f} hours, {p90/1440:.1f} days)"
            )
        else:
            print("    No data available")

        # Time to resolution statistics
        print("\n  Time to Resolution (from regression report to fix):")
        print("  " + "-" * 76)

        resolution_times = data["minutes_to_resolution"]
        if resolution_times:
            sorted_times = sorted(resolution_times)
            count = len(sorted_times)
            avg = sum(sorted_times) / count
            median = sorted_times[count // 2]
            p25 = sorted_times[int(count * 0.25)]
            p75 = sorted_times[int(count * 0.75)]
            p90 = sorted_times[int(count * 0.90)]

            print(f"    Count: {count}")
            print(
                f"    Average: {avg:.1f} minutes ({avg/60:.1f} hours, {avg/1440:.1f} days)"
            )
            print(
                f"    Median: {median:.1f} minutes ({median/60:.1f} hours, {median/1440:.1f} days)"
            )
            print(
                f"    25th percentile: {p25:.1f} minutes ({p25/60:.1f} hours, {p25/1440:.1f} days)"
            )
            print(
                f"    75th percentile: {p75:.1f} minutes ({p75/60:.1f} hours, {p75/1440:.1f} days)"
            )
            print(
                f"    90th percentile: {p90:.1f} minutes ({p90/60:.1f} hours, {p90/1440:.1f} days)"
            )
        else:
            print("    No data available")

    # Non-regression crashes section
    print("\n" + "=" * 80)
    print("NON-REGRESSION CRASH BUGS")
    print("=" * 80)

    for category_name, category_data in [
        ("NON-REGRESSION CRASHES FILED BY BOT", "non_regression_by_bot"),
        ("NON-REGRESSION CRASHES FILED BY HUMANS", "non_regression_by_humans"),
    ]:
        data = metrics[category_data]
        print(f"\n{category_name}")
        print("-" * 80)

        print(f"Total non-regression crash bugs: {data['total']}")

        print("\nResolution status:")
        print(f"  - Resolved: {data['resolved']}")
        print(f"  - Unresolved: {data['total'] - data['resolved']}")
        if data["total"] > 0:
            resolution_rate = (data["resolved"] / data["total"]) * 100
            print(f"  - Resolution rate: {resolution_rate:.1f}%")

        # Time to resolution statistics
        print("\n  Time to Resolution:")
        print("  " + "-" * 76)

        resolution_times = data["minutes_to_resolution"]
        if resolution_times:
            sorted_times = sorted(resolution_times)
            count = len(sorted_times)
            avg = sum(sorted_times) / count
            median = sorted_times[count // 2]
            p25 = sorted_times[int(count * 0.25)]
            p75 = sorted_times[int(count * 0.75)]
            p90 = sorted_times[int(count * 0.90)]

            print(f"    Count: {count}")
            print(
                f"    Average: {avg:.1f} minutes ({avg/60:.1f} hours, {avg/1440:.1f} days)"
            )
            print(
                f"    Median: {median:.1f} minutes ({median/60:.1f} hours, {median/1440:.1f} days)"
            )
            print(
                f"    25th percentile: {p25:.1f} minutes ({p25/60:.1f} hours, {p25/1440:.1f} days)"
            )
            print(
                f"    75th percentile: {p75:.1f} minutes ({p75/60:.1f} hours, {p75/1440:.1f} days)"
            )
            print(
                f"    90th percentile: {p90:.1f} minutes ({p90/60:.1f} hours, {p90/1440:.1f} days)"
            )
        else:
            print("    No data available")

    # Summary comparison
    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON")
    print("=" * 80)

    bot_data = metrics["found_by_bot"]
    human_data = metrics["found_by_humans"]

    total = bot_data["total"] + human_data["total"]
    if total > 0:
        bot_percentage = (bot_data["total"] / total) * 100
        human_percentage = (human_data["total"] / total) * 100

        print(f"\nCrash regression discovery:")
        print(f"  Bot discovered: {bot_data['total']} ({bot_percentage:.1f}%)")
        print(f"  Human discovered: {human_data['total']} ({human_percentage:.1f}%)")
        print(f"  Total: {total}")

    # Compare average discovery times
    print(f"\nAverage time to discovery:")
    for label, data in [("Bot", bot_data), ("Human", human_data)]:
        times = data["minutes_to_discovery"]
        if times:
            avg = sum(times) / len(times)
            print(
                f"  {label}: {avg:.1f} minutes ({avg/60:.1f} hours, {avg/1440:.1f} days)"
            )
        else:
            print(f"  {label}: No data")

    # Compare resolution rates
    print(f"\nResolution rates:")
    for label, data in [("Bot-discovered", bot_data), ("Human-discovered", human_data)]:
        if data["total"] > 0:
            rate = (data["resolved"] / data["total"]) * 100
            print(f"  {label}: {rate:.1f}%")
        else:
            print(f"  {label}: No data")

    # Compare average resolution times
    print(f"\nAverage time to resolution:")
    for label, data in [("Bot-discovered", bot_data), ("Human-discovered", human_data)]:
        times = data["minutes_to_resolution"]
        if times:
            avg = sum(times) / len(times)
            print(
                f"  {label}: {avg:.1f} minutes ({avg/60:.1f} hours, {avg/1440:.1f} days)"
            )
        else:
            print(f"  {label}: No data")

    print("\n" + "=" * 80)


def main():
    """Main function to analyze crash regressions and calculate metrics."""
    print("Downloading bug database...")
    db.download(bugzilla.BUGS_DB)

    print("Loading bugs...")
    bugs_list = list(bugzilla.get_bugs())
    print(f"Loaded {len(bugs_list)} total bugs")

    # First pass: Build bug cache
    bug_cache = build_bug_cache(bugs_list)

    print("\nAnalyzing crash regressions...")

    metrics = {
        "found_by_bot": {
            "total": 0,
            "with_regressed_by": 0,
            "without_regressed_by": 0,
            "minutes_to_discovery": [],
            "resolved": 0,
            "minutes_to_resolution": [],
        },
        "found_by_humans": {
            "total": 0,
            "with_regressed_by": 0,
            "without_regressed_by": 0,
            "minutes_to_discovery": [],
            "resolved": 0,
            "minutes_to_resolution": [],
        },
        "non_regression_by_bot": {
            "total": 0,
            "resolved": 0,
            "minutes_to_resolution": [],
        },
        "non_regression_by_humans": {
            "total": 0,
            "resolved": 0,
            "minutes_to_resolution": [],
        },
    }

    crash_regression_count = 0
    for bug in bugs_list:
        result = analyze_crash_regression(bug, bug_cache)
        if result is None:
            continue

        crash_regression_count += 1
        if crash_regression_count % 100 == 0:
            print(f"  Processed {crash_regression_count} crash regressions...")

        # Determine which category to update
        category = "found_by_bot" if result["filed_by_bot"] else "found_by_humans"
        data = metrics[category]

        # Update counts
        data["total"] += 1

        if result["has_regressed_by"]:
            data["with_regressed_by"] += 1
        else:
            data["without_regressed_by"] += 1

        # Update discovery time
        if result["minutes_to_discovery"] is not None:
            data["minutes_to_discovery"].append(result["minutes_to_discovery"])

        # Update resolution metrics
        if result["is_resolved"]:
            data["resolved"] += 1

            if result["minutes_to_resolution"] is not None:
                data["minutes_to_resolution"].append(result["minutes_to_resolution"])

    print(f"\nTotal crash regressions analyzed: {crash_regression_count}")

    # Analyze non-regression crashes
    print("\nAnalyzing non-regression crash bugs...")
    non_regression_crash_count = 0
    for bug in bugs_list:
        result = analyze_non_regression_crash(bug)
        if result is None:
            continue

        non_regression_crash_count += 1
        if non_regression_crash_count % 500 == 0:
            print(f"  Processed {non_regression_crash_count} non-regression crashes...")

        # Determine which category to update
        category = (
            "non_regression_by_bot"
            if result["filed_by_bot"]
            else "non_regression_by_humans"
        )
        data = metrics[category]

        # Update counts
        data["total"] += 1

        # Update resolution metrics
        if result["is_resolved"]:
            data["resolved"] += 1

            if result["minutes_to_resolution"] is not None:
                data["minutes_to_resolution"].append(result["minutes_to_resolution"])

    print(f"\nTotal non-regression crashes analyzed: {non_regression_crash_count}")
    print("\nGenerating report...")
    print_report(metrics)


if __name__ == "__main__":
    main()
