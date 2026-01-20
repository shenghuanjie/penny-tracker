python rebelsavings.py -ns
git commit -am "update data"
GIT_SSH_COMMAND='ssh -i ~/.ssh/id_rsa_public_github -o IdentitiesOnly=yes' git push
