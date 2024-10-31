# Solana-Payment-Gateway
Solana payment system using Python.

Functionality:
 - Accept payments on a freshly generated Solana wallet.
 - Auto-Deduct a set fee based on a variable set in the database.
 - Auto-Withdraw received amount to a set variable in the database.
 - Single TX fee withdrawal, the transaction sending the deposit address' funds to the main wallet contains a second instruction to deduct a set fee. If the fee variable is 0%, no instruction is added.
 - Full Database integration using MariaDB.
 - API endpoint to check if funds have been received.
 - 5% variability of deposited funds

Note:
 - Needs to be behind WSGI for stability.
 - If you fork and make changes please feel free to contribute to the main repo.
 - Code is free to use, with no limitations just give it a little star :)


