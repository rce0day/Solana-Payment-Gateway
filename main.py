from flask import Flask, request, jsonify
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solana.transaction import Transaction
from base58 import b58decode, b58encode
import requests
import mysql.connector
from mysql.connector import Error
import logging
from decimal import Decimal

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def create_connection():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            database='sol_payment',
            user='root',
            password='root'
        )
        return connection
    except Error as e:
        logger.error(f"Error connecting to MySQL database: {e}")
        return None

app = Flask(__name__)

RPC_URL = "Input RPC URL here, helius recommended"
client = Client(RPC_URL)

def get_solana_price():
    r=requests.get("https://frontend-api.pump.fun/sol-price") # dummy api (ratelimited), replace with your own
    data=r.json()
    return data["solPrice"]

def get_user_output_wallet(user_id):
    connection = create_connection()
    if connection is not None:
        try:
            cursor = connection.cursor(dictionary=True)
            query = "SELECT output_wallet FROM user_info WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            return result['output_wallet'] if result else None
        except Error as e:
            logger.error(f"Error fetching user output wallet: {e}")
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    return None

fee_account = Pubkey.from_string("Enter the public key of the fee account here, all set fees will be sent to this wallet.")

def get_user_fee_percentage(user_id):
    connection = create_connection()
    if connection is not None:
        try:
            cursor = connection.cursor(dictionary=True)
            query = "SELECT fee_percentage FROM user_info WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            return Decimal(result['fee_percentage']) if result else Decimal('2.0')  # Default to 2% if not set
        except Error as e:
            logger.error(f"Error fetching user fee percentage: {e}")
            return Decimal('2.0')  # Default to 2% if there's an error
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    return Decimal('2.0')  # Default to 2% if database connection fails

def send_funds_to_user_wallet(payment_id, user_id):
    print(f"send_funds_to_user_wallet called with payment_id: {payment_id}, user_id: {user_id}")
    logger.info(f"send_funds_to_user_wallet called with payment_id: {payment_id}, user_id: {user_id}")
    connection = create_connection()
    if connection is not None:
        try:
            cursor = connection.cursor(dictionary=True)
            query = "SELECT private_key FROM payments WHERE payment_id = %s"
            cursor.execute(query, (payment_id,))
            result = cursor.fetchone()
            
            if result:
                secret_key = result['private_key']
                full_secret_key = b58decode(secret_key)
                payer_keypair = Keypair.from_bytes(full_secret_key)
                payer_pubkey = payer_keypair.pubkey()
                
                output_wallet = get_user_output_wallet(user_id)
                if not output_wallet:
                    logger.error(f"Output wallet not found for user_id: {user_id}")
                    return False
                
                recipient_pubkey = Pubkey.from_string(output_wallet)
                
                balance = client.get_balance(payer_pubkey).value

                fee_percentage = get_user_fee_percentage(user_id)
                fee_amount_in_lamports = int(balance * (fee_percentage / 100)) if fee_percentage > 0 else 0

                transfer_amount = balance - 5000 - fee_amount_in_lamports if fee_percentage > 0 else balance - 5000

                if transfer_amount <= 0:
                    logger.error(f"Insufficient balance to cover fees and transfer for payment_id: {payment_id}")
                    return False

                transfer_ix = transfer(TransferParams(
                    from_pubkey=payer_pubkey,
                    to_pubkey=recipient_pubkey,
                    lamports=transfer_amount
                ))

                transaction = Transaction()
                transaction.add(transfer_ix)

                if fee_percentage > 0:
                    fee_transfer_ix = transfer(TransferParams(
                        from_pubkey=payer_pubkey,
                        to_pubkey=fee_account,
                        lamports=fee_amount_in_lamports
                    ))
                    transaction.add(fee_transfer_ix)
                
                recent_blockhash = client.get_latest_blockhash().value.blockhash
                transaction.recent_blockhash = recent_blockhash
                
                transaction.sign(payer_keypair)
                serialized_transaction = transaction.serialize()
                
                try:
                    signature = client.send_raw_transaction(serialized_transaction)
                    logger.info(f"Funds sent to user wallet. Transaction signature: {signature.value}")
                    return True
                except Exception as e:
                    logger.error(f"Error sending transaction: {e}")
                    return False
            else:
                logger.error(f"Payment not found: {payment_id}")
                return False
        except Error as e:
            logger.error(f"Error sending funds to user wallet: {e}")
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    return False

@app.route('/create_payment', methods=['POST'])
def create_payment():
    usd_amount = request.json['usd_amount']
    user_id = request.json['user_id']
    
    new_wallet = Keypair()
    public_key = str(new_wallet.pubkey())
    full_secret_key = new_wallet.secret() + bytes(new_wallet.pubkey())  # Concatenate private and public key
    secret_key = b58encode(full_secret_key).decode('utf-8')    
    sol_price = get_solana_price()
    sol_amount = usd_amount / sol_price
    
    connection = create_connection()
    if connection is not None:
        try:
            cursor = connection.cursor()
            query = """INSERT INTO payments (payment_id, wallet_address, sol_amount, status, user_id, private_key)
                       VALUES (%s, %s, %s, %s, %s, %s)"""
            cursor.execute(query, (public_key, public_key, sol_amount, 'pending', user_id, secret_key))
            connection.commit()
        except Error as e:
            logger.error(f"Error inserting payment into database: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    
    return jsonify({
        'wallet_address': public_key,
        'sol_amount': sol_amount,
        'payment_id': public_key
    })

@app.route('/check_payment/<payment_id>', methods=['GET'])
def check_payment_status(payment_id):
    logger.info(f"Checking payment status for payment_id: {payment_id}")
    connection = create_connection()
    if connection is not None:
        try:
            cursor = connection.cursor(dictionary=True)
            query = "SELECT sol_amount, status, user_id, funds_sent FROM payments WHERE payment_id = %s"
            cursor.execute(query, (payment_id,))
            result = cursor.fetchone()
            
            if result:
                expected_amount = Decimal(str(result['sol_amount']))
                current_status = result['status']
                user_id = result['user_id']
                funds_sent = result['funds_sent']
                
                logger.info(f"Payment found. Current status: {current_status}, Funds sent: {funds_sent}")
                
                if current_status == 'pending':
                    payment_received = check_payment(payment_id, expected_amount)
                    
                    logger.info(f"Payment received: {payment_received}")
                    
                    if payment_received:
                        new_status = 'completed'
                        update_query = "UPDATE payments SET status = %s WHERE payment_id = %s"
                        cursor.execute(update_query, (new_status, payment_id))
                        connection.commit()
                        
                        logger.info("Payment completed. Calling send_funds_to_user_wallet.")
                        send_result = send_funds_to_user_wallet(payment_id, user_id)
                        logger.info(f"send_funds_to_user_wallet result: {send_result}")
                        
                        if send_result:
                            update_query = "UPDATE payments SET funds_sent = TRUE WHERE payment_id = %s"
                            cursor.execute(update_query, (payment_id,))
                            connection.commit()
                    else:
                        logger.info("Payment not yet received.")
                elif current_status == 'completed' and not funds_sent:
                    logger.info("Payment completed but funds not sent. Calling send_funds_to_user_wallet.")
                    send_result = send_funds_to_user_wallet(payment_id, user_id)
                    logger.info(f"send_funds_to_user_wallet result: {send_result}")
                    
                    if send_result:
                        update_query = "UPDATE payments SET funds_sent = TRUE WHERE payment_id = %s"
                        cursor.execute(update_query, (payment_id,))
                        connection.commit()
                else:
                    logger.info(f"Payment already processed and funds sent. Status: {current_status}")
                
                return jsonify({
                    'payment_id': payment_id,
                    'payment_received': (current_status == 'completed'),
                    'funds_sent': funds_sent,
                    'status': current_status
                })
            else:
                logger.error(f"Payment not found: {payment_id}")
                return jsonify({'error': 'Payment not found'}), 404
        except Error as e:
            logger.error(f"Error checking payment status: {e}")
            return jsonify({'error': 'Database error'}), 500
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    else:
        logger.error("Database connection failed")
        return jsonify({'error': 'Database connection failed'}), 500

def check_payment(wallet_address, expected_amount):
    try:
        pubkey = Pubkey.from_string(wallet_address)
        balance = client.get_balance(pubkey).value
        balance_sol = Decimal(str(balance)) * Decimal('1e-9')
        if balance_sol >= expected_amount * Decimal('0.95'):  # Allow 5% variability
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking payment: {e}")
        return False

if __name__ == '__main__':
    app.run(host='localhost', port=5000)
