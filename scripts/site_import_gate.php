<?php
/**
 * Run the real site-format v2 importer against a throwaway sandbox copy
 * of the CertPassly website. Never point this at production, port 3306,
 * or the 8330 audit worktree.
 *
 * Usage: php scripts/site_import_gate.php --sandbox=/path --file=/path.json --report=/path.json [--grade-all]
 *
 * --grade-all grades a correct and a wrong response for every imported
 * question (default: the first 6) and checks that every answer key points at
 * an id or index the learner payload really has (semantic_errors).
 */
if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "CLI only\n");
    exit(2);
}

$opts = ['sandbox' => null, 'file' => null, 'report' => null, 'grade_all' => false];
foreach (array_slice($argv, 1) as $arg) {
    if (str_starts_with($arg, '--sandbox=')) {
        $opts['sandbox'] = substr($arg, 10);
    } elseif (str_starts_with($arg, '--file=')) {
        $opts['file'] = substr($arg, 7);
    } elseif (str_starts_with($arg, '--report=')) {
        $opts['report'] = substr($arg, 9);
    } elseif ($arg === '--grade-all') {
        $opts['grade_all'] = true;
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
$semantic = [];
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
        if ($versionRow && ($opts['grade_all'] || count($grade) < 6)) {
            $grader = app(App\Services\SiteFormat\SiteFormatGrader::class);
            $right = correctResponseFor($q);
            $wrong = wrongResponseFor($q, $right);
            $ok = $grader->grade($versionRow, $right);
            $bad = $grader->grade($versionRow, $wrong);
            $grade[] = [
                'question_key' => $q['question_key'],
                'type' => $q['type'],
                'correct_response' => $right,
                'wrong_response' => $wrong,
                'correct_response_accepted' => is_array($ok) ? (bool) ($ok['correct'] ?? false) : null,
                'wrong_response_rejected' => is_array($bad) ? ! ($bad['correct'] ?? true) : null,
                'manual_or_skipped' => $ok === null,
            ];
        }
        foreach (keyReferenceErrors($q) as $err) {
            $semantic[] = ['question_key' => $q['question_key'], 'type' => $q['type'], 'error' => $err];
        }
    }
}

$expected = count($doc['questions']);
$status = 'passed';
if (! ($report['valid'] ?? false) || $report['errors'] !== []) {
    $status = 'rejected';
} elseif ($rejected || $held || $notDraft || $drafts !== $expected || $semantic) {
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
    'graded_all' => $opts['grade_all'],
    'semantic_errors' => $semantic,
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
    'graded' => count($grade),
    'semantic_errors' => count($semantic),
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
    if (is_array($key) && array_is_list($key) && in_array($type, ['scenario_standalone', 'case_study_group'], true)) {
        // scenario components are graded per key part: [choice index] answers [choice index]
        return array_map('strval', $key);
    }
    if (is_array($key) && array_is_list($key) && in_array($type, ['multiple_select', 'hotspot_multi'], true)) {
        return array_map('strval', $key);
    }
    if (is_array($key) && array_is_list($key) && $type === 'ordering') {
        // the ordering component answers with item index => 1 based position
        $resp = [];
        foreach (array_values($key) as $pos => $item) {
            $resp[(string) $item] = $pos + 1;
        }

        return $resp;
    }
    if (is_string($key) || is_int($key)) {
        return ['value' => (string) $key];
    }
    if (is_array($key)) {
        return $key;
    }

    return ['value' => ''];
}

/** A near miss: the right response with exactly one part changed. */
function wrongResponseFor(array $q, array $right): array
{
    $type = (string) ($q['type'] ?? '');
    $ids = choiceIds($q);
    if (array_key_exists('value', $right) && count($right) === 1) {
        foreach ($ids as $id) {
            if ((string) $id !== (string) $right['value']) {
                return ['value' => (string) $id];
            }
        }

        return ['value' => '__wrong__'];
    }
    if (in_array($type, ['scenario_standalone', 'case_study_group'], true)) {
        foreach ($ids as $id) {
            if ((string) $id !== (string) ($right[0] ?? '')) {
                return [(string) $id];
            }
        }

        return ['__wrong__'];
    }
    if (in_array($type, ['multiple_select', 'hotspot_multi'], true)) {
        // a set: drop one member, or add one that is not in it
        if (count($right) > 1) {
            return array_slice($right, 1);
        }
        foreach ($ids as $id) {
            if (! in_array((string) $id, $right, true)) {
                return array_merge($right, [(string) $id]);
            }
        }

        return [];
    }
    $keys = array_keys($right);
    $wrong = $right;
    if ($type === 'ordering' && count($keys) >= 2) {
        [$a, $b] = [$keys[0], $keys[1]];
        $wrong[$a] = $right[$b];
        $wrong[$b] = $right[$a];

        return $wrong;
    }
    $first = $keys[0] ?? null;
    if ($first === null) {
        return ['value' => '__wrong__'];
    }
    foreach (partValues($q, (string) $first) as $v) {
        if ((string) $v !== (string) $right[$first]) {
            $wrong[$first] = $v;

            return $wrong;
        }
    }
    $wrong[$first] = '__wrong__';

    return $wrong;
}

/** Ids a single or set answer can take. */
function choiceIds(array $q): array
{
    $learner = $q['learner'] ?? [];
    $regions = $learner['interaction']['hotspot_regions'] ?? null;
    if (is_array($regions)) {
        return array_map(fn ($r) => (string) ($r['id'] ?? ''), $regions);
    }
    $blanks = $learner['interaction']['cloze']['blanks'] ?? null;
    if (is_array($blanks) && count($blanks) === 1) {
        return array_map(fn ($o) => (string) ($o['id'] ?? ''), $blanks[0]['options'] ?? []);
    }

    return array_map('strval', array_keys($learner['choices'] ?? []));
}

/** Values one keyed part can take (matrix columns, blank options, slots, targets). */
function partValues(array $q, string $part): array
{
    $i = $q['learner']['interaction'] ?? [];
    if (isset($i['matrix']['columns'])) {
        return array_map(fn ($c) => (string) $c['id'], $i['matrix']['columns']);
    }
    if (isset($i['cloze']['blanks'])) {
        foreach ($i['cloze']['blanks'] as $b) {
            if ((string) $b['id'] === $part) {
                return array_map(fn ($o) => (string) $o['id'], $b['options'] ?? []);
            }
        }
    }
    if (isset($i['drag_slots'])) {
        return array_map('strval', array_keys($i['drag_slots']));
    }
    if (isset($i['matching_pairs'])) {
        return array_map('strval', array_keys(matchingTargets($i['matching_pairs'])));
    }

    return [];
}

/** Matching targets as the site lists them: unique, natural case-insensitive sort. */
function matchingTargets(array $pairs): array
{
    $t = [];
    foreach ($pairs as $p) {
        $t[] = is_array($p) ? (string) ($p[1] ?? '') : '';
    }
    $t = array_values(array_unique($t));
    sort($t, SORT_NATURAL | SORT_FLAG_CASE);

    return $t;
}

/** Every key part must point at a row, column, option, slot, target, region or item the learner sees. */
function keyReferenceErrors(array $q): array
{
    $type = (string) ($q['type'] ?? '');
    $key = $q['answer']['answer_key'] ?? null;
    $i = $q['learner']['interaction'] ?? [];
    $choices = $q['learner']['choices'] ?? [];
    $errs = [];
    $in = fn ($v, array $allowed) => in_array((string) $v, array_map('strval', $allowed), true);
    switch ($type) {
        case 'single_choice':
        case 'true_false':
        case 'image_based_choice':
        case 'multiple_select':
        case 'scenario_standalone':
        case 'case_study_group':
            foreach ((array) $key as $v) {
                if (! $in($v, array_keys($choices))) {
                    $errs[] = "answer $v is not a choice index";
                }
            }
            break;
        case 'yes_no_matrix':
        case 'single_choice_matrix':
            $rows = array_map(fn ($r) => $r['id'], $i['matrix']['rows'] ?? []);
            $cols = array_map(fn ($c) => $c['id'], $i['matrix']['columns'] ?? []);
            foreach ((array) $key as $r => $c) {
                if (! $in($r, $rows) || ! $in($c, $cols)) {
                    $errs[] = "row $r column $c is not in the grid";
                }
            }
            if (count((array) $key) !== count($rows)) {
                $errs[] = 'not every grid row has an answer';
            }
            break;
        case 'inline_dropdown':
        case 'multi_blank_dropdown':
            $opts = [];
            foreach ($i['cloze']['blanks'] ?? [] as $b) {
                $opts[(string) $b['id']] = array_map(fn ($o) => $o['id'], $b['options'] ?? []);
            }
            $k = is_array($key) && array_is_list($key) && count($opts) === 1 ? [array_key_first($opts) => $key[0]] : (array) $key;
            foreach ($k as $b => $o) {
                if (! isset($opts[(string) $b]) || ! $in($o, $opts[(string) $b])) {
                    $errs[] = "blank $b option $o is not offered";
                }
            }
            if (count($k) !== count($opts)) {
                $errs[] = 'not every blank has an answer';
            }
            break;
        case 'ordering':
            $n = count($i['ordering'] ?? []);
            $k = array_map('intval', (array) $key);
            $want = range(0, max(0, $n - 1));
            $got = $k;
            sort($got);
            if ($n < 2 || $got !== $want) {
                $errs[] = 'ordering key is not a permutation of the items';
            }
            break;
        case 'matching':
            $pairs = $i['matching_pairs'] ?? [];
            $targets = matchingTargets($pairs);
            foreach ($pairs as $idx => $p) {
                $want = array_search((string) $p[1], $targets, true);
                $got = ((array) $key)[(string) $idx] ?? ((array) $key)[$idx] ?? null;
                if ($got === null || (string) $got !== (string) $want) {
                    $errs[] = "item $idx key $got does not name target \"".$p[1]."\" (index $want after site sort)";
                }
            }
            break;
        case 'categorization':
        case 'drag_drop':
            $slots = array_keys($i['drag_slots'] ?? []);
            foreach ((array) $key as $item => $slot) {
                if (! $in($item, array_keys($choices)) || ! $in($slot, $slots)) {
                    $errs[] = "item $item slot $slot is not offered";
                }
            }
            if (count((array) $key) !== count($choices)) {
                $errs[] = 'not every item has a slot';
            }
            break;
        case 'hotspot_single':
        case 'hotspot_multi':
            $ids = array_map(fn ($r) => $r['id'], $i['hotspot_regions'] ?? []);
            foreach ((array) $key as $v) {
                if (! $in($v, $ids)) {
                    $errs[] = "region $v is not on the image";
                }
            }
            break;
    }

    return $errs;
}
