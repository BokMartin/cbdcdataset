<?php
// CBDC Dataset — feedback form handler.
// Sends submissions from contribute.html by email; no data is stored on the server.

$to = "dominikstroukal@gmail.com";
$site = "CBDC Dataset (cbdcdataset.org)";

function clean($v) {
    return trim(str_replace(array("\r", "\n"), " ", (string) $v));
}

if ($_SERVER["REQUEST_METHOD"] !== "POST") {
    header("Location: contribute.html");
    exit;
}

// Honeypot: real visitors never fill this hidden field.
if (!empty($_POST["website"])) {
    header("Location: thanks.html");
    exit;
}

$name         = clean($_POST["name"] ?? "");
$email        = clean($_POST["email"] ?? "");
$jurisdiction = clean($_POST["jurisdiction"] ?? "");
$message      = trim($_POST["message"] ?? "");

if ($message === "") {
    header("Location: contribute.html?error=empty#feedback-form");
    exit;
}

$subject = "[$site] Feedback" . ($jurisdiction !== "" ? " — $jurisdiction" : "");

$body  = "New feedback submitted on cbdcdataset.org\n\n";
$body .= "Name: " . ($name !== "" ? $name : "(not provided)") . "\n";
$body .= "Email: " . ($email !== "" ? $email : "(not provided)") . "\n";
$body .= "Jurisdiction/document: " . ($jurisdiction !== "" ? $jurisdiction : "(not provided)") . "\n\n";
$body .= "Message:\n$message\n";

$headers = "From: no-reply@cbdcdataset.org\r\n";
if ($email !== "" && filter_var($email, FILTER_VALIDATE_EMAIL)) {
    $headers .= "Reply-To: " . $email . "\r\n";
}

@mail($to, $subject, $body, $headers);

header("Location: thanks.html");
exit;
