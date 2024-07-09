from bugbug import db, bugzilla

# Download the Bugzilla database
db.download(bugzilla.BUGS_DB)

# Function to process bug history
def process_bug_history():
    counter = 0
    for bug in bugzilla.get_bugs():
        for transaction in bug['history']:
            if transaction['who'] == 'release-mgmt-account-bot@mozilla.tld':
                for change in transaction['changes']:
                    if change['field_name'] == 'resolution' and change['added'] == 'INVALID':
                        print(f"Bug ID: {bug['id']}")
                        print(f"Transaction: {transaction}")
                        counter += 1
    
    return counter
if __name__ == "__main__":
    db.download(bugzilla.BUGS_DB)
    counter = process_bug_history()
    print(f"Number of bugs marked as false positives: {counter}")