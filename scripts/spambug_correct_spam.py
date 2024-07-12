from bugbug import db, bugzilla

def contains_spam_comment(comments, comment_text):
    for comment in comments:
        if comment_text in comment['text']:
            return True
    return False

def search_correct_spam():
    comment_text = """If you think the bot is wrong, please reopen the bug and move it back to its prior component."""
    counter = 0

    for bug in bugzilla.get_bugs():
        if bug['resolution'] == 'INVALID' and contains_spam_comment(bug['comments'], comment_text):
            print(f"Bug ID: {bug['id']}")
            counter += 1

    return counter

if __name__ == "__main__":
    db.register(
        bugzilla.BUGS_DB,
        "https://community-tc.services.mozilla.com/api/index/v1/task/project.bugbug.data_bugs.latest/artifacts/public/bugs.json.zst",
        10
    )
    db.download(bugzilla.BUGS_DB)
    counter = search_correct_spam()
    print(f"Number of bugs marked as spam: {counter}")
