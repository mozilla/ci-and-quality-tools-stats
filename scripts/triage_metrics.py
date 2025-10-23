#!/usr/bin/env python3
"""
Script to measure bug triage metrics related to external contributors and needinfo usage.

Metrics measured:
- How long between opening the bug by external person and first needinfo to the external person
- In how many bugs there have been needinfo on external person
- In how many bugs the external person doesn't answer needinfo and we close the bug without fixing it
- Are there bugs where the triage process failed and we had to uplift the fix to release?
"""

import re
from datetime import datetime
from collections import defaultdict
from bugbug import db, bugzilla


# Regex pattern to extract needinfo requestee
NI_PAT = re.compile(r"needinfo\?\((.*?)\)")

# Mozilla email domains to identify Mozilla employees
MOZILLA_DOMAINS = [
    "@mozilla.com",
    "@mozilla.org",
    "@mozillafoundation.org",
]

# Date range for analysis
OLDEST_BUG = "2025-01-01T00:00:00Z"


def is_external_user(email):
    """Check if a user email is external (not a Mozilla employee)."""
    if not email:
        return False
    email_lower = email.lower()
    return not any(domain in email_lower for domain in MOZILLA_DOMAINS)


def parse_datetime(dt_str):
    """Parse Bugzilla datetime string to datetime object."""
    if not dt_str:
        return None
    # Handle both formats: with and without microseconds
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def get_needinfo_events(bug):
    """
    Extract all needinfo events from bug history.
    Returns a list of events with (timestamp, action, requestee, setter) tuples.
    action can be 'added' or 'removed'
    """
    events = []

    # Check current flags for any pending needinfos
    current_needinfos = set()
    if "flags" in bug:
        for flag in bug["flags"]:
            if flag["name"] == "needinfo" and flag.get("requestee"):
                current_needinfos.add(flag["requestee"])

    # Parse history for needinfo changes
    if "history" in bug:
        for event in bug["history"]:
            for change in event["changes"]:
                if change["field_name"] == "flagtypes.name":
                    setter = event.get("who", "")
                    timestamp = parse_datetime(event["when"])

                    # Extract removed needinfos
                    removed_needinfos = NI_PAT.findall(change.get("removed", ""))
                    for requestee in removed_needinfos:
                        events.append((timestamp, "removed", requestee, setter))

                    # Extract added needinfos
                    added_needinfos = NI_PAT.findall(change.get("added", ""))
                    for requestee in added_needinfos:
                        events.append((timestamp, "added", requestee, setter))

    return events


def analyze_bug(bug):
    """
    Analyze a single bug and return metrics.
    Returns a dict with analysis results or None if bug should be skipped.
    """
    creation_time = parse_datetime(bug.get("creation_time"))
    if not creation_time:
        return None

    # Filter by date
    oldest_bug_date = parse_datetime(OLDEST_BUG)
    if creation_time < oldest_bug_date:
        return None

    creator = bug.get("creator", "")
    is_external = is_external_user(creator)

    # Get needinfo events
    needinfo_events = get_needinfo_events(bug)

    # Track first needinfo times
    first_needinfo_on_author = None
    first_needinfo_on_others = None
    first_needinfo_overall = None

    # Track needinfo answers - mapping of (requestee -> (set_time, setter))
    pending_needinfos = {}
    needinfo_on_author_answered = True  # Assume answered unless we find unanswered

    for timestamp, action, requestee, setter in needinfo_events:
        if action == "added":
            pending_needinfos[requestee] = (timestamp, setter)

            # Track first needinfo times
            if first_needinfo_overall is None:
                first_needinfo_overall = timestamp

            if requestee == creator:
                if first_needinfo_on_author is None:
                    first_needinfo_on_author = timestamp
            else:
                if first_needinfo_on_others is None:
                    first_needinfo_on_others = timestamp

        elif action == "removed":
            # Check if needinfo was cleared by the requestee themselves
            if requestee in pending_needinfos:
                if setter == requestee:
                    # Answered by themselves
                    del pending_needinfos[requestee]
                else:
                    # Cleared by someone else - still counts as unanswered
                    del pending_needinfos[requestee]

    # Check if there are any unanswered needinfos on the author
    if creator in pending_needinfos:
        needinfo_on_author_answered = False

    # Calculate time differences in minutes
    minutes_to_first_needinfo_on_author = None
    if first_needinfo_on_author:
        minutes_to_first_needinfo_on_author = (first_needinfo_on_author - creation_time).total_seconds() / 60

    minutes_to_first_needinfo_on_others = None
    if first_needinfo_on_others:
        minutes_to_first_needinfo_on_others = (first_needinfo_on_others - creation_time).total_seconds() / 60

    minutes_to_first_needinfo_overall = None
    if first_needinfo_overall:
        minutes_to_first_needinfo_overall = (first_needinfo_overall - creation_time).total_seconds() / 60

    # Check bug status
    status = bug.get("status", "")
    resolution = bug.get("resolution", "")
    is_closed = status in ("RESOLVED", "VERIFIED", "CLOSED")
    is_closed_with_fix = is_closed and resolution == "FIXED"
    is_closed_without_fix = is_closed and resolution != "FIXED"

    # Check for uplifts (approval flags)
    has_uplift = False
    if "history" in bug:
        for event in bug["history"]:
            for change in event["changes"]:
                if change["field_name"] == "flagtypes.name":
                    added = change.get("added", "")
                    # Look for approval flags
                    if any(approval in added for approval in [
                        "approval-mozilla-release",
                        "approval-mozilla-beta",
                        "approval-mozilla-esr"
                    ]):
                        has_uplift = True
                        break
            if has_uplift:
                break

    return {
        "is_external": is_external,
        "minutes_to_first_needinfo_on_author": minutes_to_first_needinfo_on_author,
        "minutes_to_first_needinfo_on_others": minutes_to_first_needinfo_on_others,
        "minutes_to_first_needinfo_overall": minutes_to_first_needinfo_overall,
        "is_closed": is_closed,
        "is_closed_with_fix": is_closed_with_fix,
        "is_closed_without_fix": is_closed_without_fix,
        "needinfo_on_author_answered": needinfo_on_author_answered,
        "has_uplift": has_uplift,
    }


def print_report(metrics):
    """Print a comprehensive report of the metrics."""
    print("\n" + "=" * 80)
    print("BUG TRIAGE METRICS REPORT")
    print("=" * 80)
    print(f"Analysis period: From {OLDEST_BUG}")
    print("=" * 80)

    for category_name, category_data in [
        ("BUGS FILED BY EXTERNAL CONTRIBUTORS", "bugs_filed_by_externals"),
        ("BUGS FILED BY MOZILLA EMPLOYEES", "bugs_filed_by_mozilla")
    ]:
        data = metrics[category_data]
        print(f"\n{category_name}")
        print("-" * 80)

        print(f"Total bugs: {data['total']}")
        print(f"Closed bugs: {data['bugs_closed']}")
        print(f"  - Closed with fix (FIXED): {data['bugs_closed_with_fix']}")
        print(f"  - Closed without fix: {data['bugs_closed_without_fix']}")

        if data['bugs_closed'] > 0:
            fix_rate = (data['bugs_closed_with_fix'] / data['bugs_closed']) * 100
            print(f"  - Fix rate: {fix_rate:.1f}%")

        print(f"\nBugs closed without fix where needinfo on author was not answered: "
              f"{data['bugs_closed_without_fix_and_needinfo_on_author_not_answered']}")

        print(f"Bugs with unanswered needinfo on author that had uplift: "
              f"{data['bugs_with_needinfo_on_author_not_answered_and_uplift']}")

        # Needinfo timing statistics
        print("\n  Needinfo Response Times (minutes):")
        print("  " + "-" * 76)

        for time_type, time_list in [
            ("Time to first needinfo on bug author", data['minutes_to_first_needinfo_on_author']),
            ("Time to first needinfo on others", data['minutes_to_first_needinfo_on_others']),
            ("Time to any first needinfo", data['minutes_to_first_needinfo_overall']),
        ]:
            print(f"\n  {time_type}:")
            if time_list:
                sorted_times = sorted(time_list)
                count = len(sorted_times)
                avg = sum(sorted_times) / count
                median = sorted_times[count // 2]
                p25 = sorted_times[int(count * 0.25)]
                p75 = sorted_times[int(count * 0.75)]
                p90 = sorted_times[int(count * 0.90)]

                print(f"    Count: {count}")
                print(f"    Average: {avg:.1f} minutes ({avg/60:.1f} hours)")
                print(f"    Median: {median:.1f} minutes ({median/60:.1f} hours)")
                print(f"    25th percentile: {p25:.1f} minutes ({p25/60:.1f} hours)")
                print(f"    75th percentile: {p75:.1f} minutes ({p75/60:.1f} hours)")
                print(f"    90th percentile: {p90:.1f} minutes ({p90/60:.1f} hours)")
            else:
                print("    No data available")

    # Summary comparison
    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON")
    print("=" * 80)

    ext_data = metrics["bugs_filed_by_externals"]
    moz_data = metrics["bugs_filed_by_mozilla"]

    print(f"\nTotal bugs analyzed:")
    print(f"  External contributors: {ext_data['total']}")
    print(f"  Mozilla employees: {moz_data['total']}")

    if ext_data['bugs_closed'] > 0 and moz_data['bugs_closed'] > 0:
        ext_fix_rate = (ext_data['bugs_closed_with_fix'] / ext_data['bugs_closed']) * 100
        moz_fix_rate = (moz_data['bugs_closed_with_fix'] / moz_data['bugs_closed']) * 100
        print(f"\nFix rates for closed bugs:")
        print(f"  External contributors: {ext_fix_rate:.1f}%")
        print(f"  Mozilla employees: {moz_fix_rate:.1f}%")

    # Compare average response times
    print(f"\nAverage time to first needinfo on bug author:")
    for label, data in [("External", ext_data), ("Mozilla", moz_data)]:
        times = data['minutes_to_first_needinfo_on_author']
        if times:
            avg = sum(times) / len(times)
            print(f"  {label}: {avg:.1f} minutes ({avg/60:.1f} hours)")
        else:
            print(f"  {label}: No data")

    print("\n" + "=" * 80)



def main():
    """Main function to analyze bugs and calculate metrics."""
    print("Downloading bug database...")
    db.download(bugzilla.BUGS_DB)

    print("Analyzing bugs...")

    metrics = {
        "bugs_filed_by_externals": {
            "total": 0,
            "minutes_to_first_needinfo_on_author": [],
            "minutes_to_first_needinfo_on_others": [],
            "minutes_to_first_needinfo_overall": [],
            "bugs_closed": 0,
            "bugs_closed_with_fix": 0,
            "bugs_closed_without_fix": 0,
            "bugs_closed_without_fix_and_needinfo_on_author_not_answered": 0,
            "bugs_with_needinfo_on_author_not_answered_and_uplift": 0,
        },
        "bugs_filed_by_mozilla": {
            "total": 0,
            "minutes_to_first_needinfo_on_author": [],
            "minutes_to_first_needinfo_on_others": [],
            "minutes_to_first_needinfo_overall": [],
            "bugs_closed": 0,
            "bugs_closed_with_fix": 0,
            "bugs_closed_without_fix": 0,
            "bugs_closed_without_fix_and_needinfo_on_author_not_answered": 0,
            "bugs_with_needinfo_on_author_not_answered_and_uplift": 0,
        },
    }

    bug_count = 0
    for bug in bugzilla.get_bugs():
        result = analyze_bug(bug)
        if result is None:
            continue

        bug_count += 1
        if bug_count % 1000 == 0:
            print(f"  Processed {bug_count} bugs...")

        # Determine which category to update
        category = "bugs_filed_by_externals" if result["is_external"] else "bugs_filed_by_mozilla"
        data = metrics[category]

        # Update counts
        data["total"] += 1

        # Update needinfo timing lists
        if result["minutes_to_first_needinfo_on_author"] is not None:
            data["minutes_to_first_needinfo_on_author"].append(
                result["minutes_to_first_needinfo_on_author"]
            )

        if result["minutes_to_first_needinfo_on_others"] is not None:
            data["minutes_to_first_needinfo_on_others"].append(
                result["minutes_to_first_needinfo_on_others"]
            )

        if result["minutes_to_first_needinfo_overall"] is not None:
            data["minutes_to_first_needinfo_overall"].append(
                result["minutes_to_first_needinfo_overall"]
            )

        # Update closure metrics
        if result["is_closed"]:
            data["bugs_closed"] += 1

            if result["is_closed_with_fix"]:
                data["bugs_closed_with_fix"] += 1
            elif result["is_closed_without_fix"]:
                data["bugs_closed_without_fix"] += 1

                # Check if closed without fix and needinfo on author was not answered
                if not result["needinfo_on_author_answered"]:
                    data["bugs_closed_without_fix_and_needinfo_on_author_not_answered"] += 1

        # Check for uplift with unanswered needinfo on author
        if result["has_uplift"] and not result["needinfo_on_author_answered"]:
            data["bugs_with_needinfo_on_author_not_answered_and_uplift"] += 1

    print(f"\nTotal bugs processed: {bug_count}")
    print("\nGenerating report...")
    print_report(metrics)


if __name__ == "__main__":
    main()
