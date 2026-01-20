python rebelsavings.py -ns
cp report.html ../../index.html
GIT_SSH_COMMAND='ssh -i ~/.ssh/id_rsa_public_github -o IdentitiesOnly=yes' git push
