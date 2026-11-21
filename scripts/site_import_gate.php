<?php
/**
 * Run the real site-format v2 importer against a throwaway sandbox copy
 * of the CertPassly website. Never point this at production, port 3306,
 * or the 8330 audit worktree.
 *
 * Usage: php scripts/site_import_gate.php --sandbox=/path --file=/path.json --report=/path.json
 */
if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "CLI only\n");
    exit(2);
}

$opts = ['sandbox' => null, 'file' => null, 'report' => null];
foreach (array_slice($argv, 1) as $arg) {
    if (str_starts_with($arg, '--sandbox=')) {
        $opts['sandbox'] = substr($arg, 10);
    } elseif (str_starts_with($arg, '--file=')) {
        $opts['file'] = substr($arg, 7);
    } elseif (str_starts_with($arg, '--report=')) {
        $opts['report'] = substr($arg, 9);
    } else {
        fwrite(STDERR, "Unknown argument: $arg\n");
        exit(2);
    }
}
foreach (['sandbox', 'file', 'report'] as $req) {
    if (empty($opts[$req])) {
        fwrite(STDERR, "Missing --$req=\n");
        exit(2);
    }
}

$sandbox = realpath($opts['sandbox']);
$file = realpath($opts['file']);
if ($sandbox === false || !is_file($sandbox.'/artisan')) {
    fwrite(STDERR, "Sandbox is not a Laravel app\n");
    exit(2);
}
if ($file === false || !is_file($file)) {
    fwrite(STDERR, "Site v2 file not found\n");
    exit(2);
}
$marker = $sandbox.'/SANDBOX-SOURCE.txt';
if (!is_file($marker) || !str_contains((string) file_get_contents($marker), 'a3009daa5')) {
    fwrite(STDERR, "Refusing to run: sandbox is missing SANDBOX-SOURCE.txt for commit a3009daa5\n");
    exit(2);
}
$envPath = $sandbox.'/.env';
$env = is_file($envPath) ? (string) file_get_contents($envPath) : '';
if (str_contains($env, '3306') || str_contains($env, ':8330')) {
    fwrite(STDERR, "Refusing to run: sandbox .env mentions port 3306 or 8330\n");
    exit(2);
}
if (!preg_match('/^DB_CONNECTION=sqlite\s*$/m', $env)) {
    fwrite(STDERR, "Refusing to run: sandbox must use sqlite, not the shared MariaDB\n");
    exit(2);
}

require $sandbox.'/vendor/autoload.php';
$app = require $sandbox.'/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

$doc = json_decode((string) file_get_contents($file), true, 512, JSON_THROW_ON_ERROR);
if (!is_array($doc) || !is_array($doc['exam'] ?? null) || !is_array($doc['questions'] ?? null)) {
    fwrite(STDERR, "Site file is not a v2 exam object\n");
    exit(2);
}

$code = (string) $doc['exam']['exam_code'];
$vendorSlug = strtolower((string) ($doc['exam']['vendor_slug'] ?? $doc['exam']['vendor'] ?? 'vendor'));
$vendorSlug = preg_replace('/[^a-z0-9-]+/', '-', $vendorSlug) ?: 'vendor';
$vendorName = (string) ($doc['exam']['vendor'] ?? $vendorSlug);
$examName = (string) ($doc['exam']['name'] ?? $doc['exam']['exam_name'] ?? $code);

$vendor = App\Models\Vendor::query()->firstOrCreate(
    ['slug' => $vendorSlug],
    ['name' => $vendorName, 'status' => 'active', 'short_name' => $vendorName]
);
$cert = App\Models\Certification::query()->firstOrCreate(
    ['code' => $code.'-CERT'],
    [
        'vendor_id' => $vendor->id,
        'name' => $examName,
        'slug' => $vendorSlug.'-'.$code.'-cert',
        'status' => 'draft',
        'level' => 'associate',
    ]
);
$exam = App\Models\Exam::query()->where('exam_code', $code)->orWhere('code', $code)->first();
if (! $exam) {
    $exam = new App\Models\Exam();
    $exam->forceFill([
        'vendor_id' => $vendor->id,
        'certification_id' => $cert->id,
        'slug' => $vendorSlug.'-'.$code,
        'code' => $code,
        'name' => $examName,
        'exam_code' => $code,
        'exam_name' => $examName,
        'status' => 'draft',
        'is_active' => true,
        'price_cents' => 0,
    ])->save();
}

$version = App\Models\ExamVersion::query()->where('exam_id', $exam->id)->where('is_current', true)->first();
if (! $version) {
    $version = new App\Models\ExamVersion();
    $attrs = [
        'exam_id' => $exam->id,
        'version_code' => 'sandbox-v1',
        'effective_date' => now()->toDateString(),
        'is_current' => true,
        'status' => 'draft',
    ];
    if (in_array('uuid', $version->getConnection()->getSchemaBuilder()->getColumnListing($version->getTable()), true)) {
        $attrs['uuid'] = (string) Illuminate\Support\Str::uuid();
    }
    if (in_array('version_number', $version->getConnection()->getSchemaBuilder()->getColumnListing($version->getTable()), true)) {
        $attrs['version_number'] = '1.0';
    }
    $version->forceFill($attrs)->save();
}

$domainNames = [];
foreach ($doc['questions'] as $q) {
    $name = (string) ($q['domain'] ?? 'Unassigned');
    $domainNames[$name] = true;
}
$n = 1;
foreach (array_keys($domainNames) as $name) {
    $exists = App\Models\ExamDomain::query()->where('exam_id', $exam->id)->where('name', $name)->first();
    if (! $exists) {
        App\Models\ExamDomain::query()->create([
            'exam_id' => $exam->id,
            'exam_version_id' => $version->id,
            'domain_number' => $n,
            'name' => $name,
            'weight_percentage' => 0,
            'status' => 'draft',
        ]);
    }
    $n++;
}

$importer = app(App\Services\SiteFormat\SiteFormatImporter::class);
$report = $importer->import($doc, basename($file), false);

$created = [];
$rejected = [];
$held = [];
$other = [];
foreach ($report['questions'] ?? [] as $row) {
    $result = $row['result'] ?? 'unknown';
    if (in_array($result, ['created', 'updated', 'unchanged', 'would_save'], true)) {
        $created[] = $row;
    } elseif ($result === 'held') {
        $held[] = $row;
    } elseif ($result === 'error' || ! empty($report['errors'])) {
        $rejected[] = $row + ['message' => $row['message'] ?? implode('; ', $report['errors'] ?? [])];
    } else {
        $other[] = $row;
    }
}

$drafts = 0;
$notDraft = [];
$grade = [];
if ($report['valid'] ?? false) {
    foreach ($doc['questions'] as $q) {
        $question = App\Models\Question::query()->where('question_key', $q['question_key'])->first();
        if (! $question) {
            $notDraft[] = ['question_key' => $q['question_key'], 'reason' => 'not in database'];
            continue;
        }
        if ($question->status !== 'draft' || $question->published_version_id) {
            $notDraft[] = ['question_key' => $q['question_key'], 'reason' => 'status='.$question->status];
            continue;
        }
        $drafts++;
        $versionRow = App\Models\QuestionVersion::query()->where('question_id', $question->id)->latest('id')->first();
        if ($versionRow && count($grade) < 6) {
            $grader = app(App\Services\SiteFormat\SiteFormatGrader::class);
            $ok = $grader->grade($versionRow, correctResponseFor($q));
            $bad = $grader->grade($versionRow, ['value' => '__wrong__']);
            $grade[] = [
                'question_key' => $q['question_key'],
                'type' => $q['type'],
                'correct_response_accepted' => is_array($ok) ? (bool) ($ok['correct'] ?? false) : null,
                'wrong_response_rejected' => is_array($bad) ? ! ($bad['correct'] ?? true) : null,
                'manual_or_skipped' => $ok === null,
            ];
        }
    }
}

$expected = count($doc['questions']);
$status = 'passed';
if (! ($report['valid'] ?? false) || $report['errors'] !== []) {
    $status = 'rejected';
} elseif ($rejected || $held || $notDraft || $drafts !== $expected) {
    $status = 'failed';
}

$out = [
    'schema_version' => 1,
    'status' => $status,
    'exam_code' => $code,
    'valid' => (bool) ($report['valid'] ?? false),
    'schema_errors' => $report['errors'] ?? [],
    'warnings' => $report['warnings'] ?? [],
    'exported_question_count' => $expected,
    'created_count' => count($created),
    'held_count' => count($held),
    'rejected_count' => count($rejected) + count($notDraft),
    'draft_count' => $drafts,
    'held' => $held,
    'rejected' => array_values(array_merge($rejected, $notDraft)),
    'grading_samples' => $grade,
    'exam_status' => $exam->fresh()->status,
    'published' => false,
];
$dir = dirname($opts['report']);
if (!is_dir($dir)) {
    mkdir($dir, 0777, true);
}
file_put_contents($opts['report'], json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)."\n");
fwrite(STDOUT, json_encode([
    'status' => $out['status'],
    'exam_code' => $code,
    'exported_question_count' => $expected,
    'created_count' => $out['created_count'],
    'draft_count' => $out['draft_count'],
    'held_count' => $out['held_count'],
    'rejected_count' => $out['rejected_count'],
    'report' => $opts['report'],
], JSON_UNESCAPED_SLASHES)."\n");
exit($status === 'passed' ? 0 : 2);

function correctResponseFor(array $q): array
{
    $key = $q['answer']['answer_key'] ?? null;
    $type = (string) ($q['type'] ?? '');
    if (is_array($key) && array_is_list($key) && in_array($type, ['single_choice', 'true_false', 'image_based_choice', 'inline_dropdown', 'hotspot_single'], true)) {
        return ['value' => (string) $key[0]];
    }
    if (is_array($key) && array_is_list($key) && in_array($type, ['multiple_select', 'hotspot_multi', 'ordering'], true)) {
        return array_map('strval', $key);
    }
    if (is_string($key) || is_int($key)) {
        return ['value' => (string) $key];
    }
    if (is_array($key)) {
        return $key;
    }
    return ['value' => ''];
}
