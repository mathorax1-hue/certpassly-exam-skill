<?php
/**
 * Data setup for the THROWAWAY client-test copy of the import sandbox.
 * Publishes the imported questions, sets exam facts the mock needs, and
 * creates one learner with an all-access entitlement. No site code changes.
 * Usage: php setup_client_site.php /workspace/client-site
 */
$site = realpath($argv[1] ?? '');
if (!$site || !str_contains((string) @file_get_contents($site.'/SANDBOX-SOURCE.txt'), 'CLIENT TEST COPY')) {
    fwrite(STDERR, "refusing: not the client test copy\n"); exit(2);
}
$env = (string) file_get_contents($site.'/.env');
if (str_contains($env, '3306') || str_contains($env, ':8330') || !preg_match('/^DB_CONNECTION=sqlite\s*$/m', $env)) {
    fwrite(STDERR, "refusing: copy must use sqlite, never 3306 or 8330\n"); exit(2);
}
require $site.'/vendor/autoload.php';
$app = require $site.'/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\{Exam, Question, QuestionVersion, User, Entitlement};
use Illuminate\Support\Str;

$out = ['published' => [], 'gate_refused' => []];
foreach (Exam::all() as $exam) {
    $n = 0;
    foreach (Question::where('exam_id', $exam->id)->get() as $q) {
        $v = QuestionVersion::where('question_id', $q->id)->latest('id')->first();
        if (!$v) continue;
        $res = null;
        try { $res = app(App\Services\PublicationService::class)->publishQuestion($q, null, 'client test'); } catch (Throwable $e) { $res = ['allowed' => false, 'failed' => [$e->getMessage()]]; }
        if (!($res['allowed'] ?? false)) {
            // the editorial gate needs review data the raw import does not carry; this copy is throwaway
            $out['gate_refused'][$exam->code] = ($out['gate_refused'][$exam->code] ?? 0) + 1;
            $out['gate_reason_sample'][$exam->code] = array_slice((array) ($res['failed'] ?? []), 0, 3);
            $v->forceFill(['editorial_status' => 'approved'])->save();
            $q->forceFill(['status' => 'published', 'published_version_id' => $v->id, 'working_version_id' => $v->id,
                'published_at' => now(), 'reviewed_at' => now()])->save();
        }
        $n++;
    }
    $exam->forceFill(['status' => 'published', 'is_active' => true,
        'duration_minutes' => $exam->duration_minutes ?: 120,
        'question_count' => $exam->question_count ?: min($n, 50)])->save();
    $out['published'][$exam->code] = $n;
}
$user = User::where('email', 'learner@client-test.local')->first();
if (!$user) {
    $user = new User();
    $user->forceFill(['uuid' => (string) Str::uuid(), 'name' => 'Client Test Learner', 'email' => 'learner@client-test.local',
        'password' => bcrypt('client-test-only'), 'email_verified_at' => now(), 'role' => 'student', 'status' => 'active'])->save();
}
// the anti-sharing device limit suspends a learner seen on many new browsers; reset it for repeat runs
$user->forceFill(['status' => 'active'])->save();
foreach (['user_device_events', 'user_devices'] as $t) {
    if (Illuminate\Support\Facades\Schema::hasTable($t)) { Illuminate\Support\Facades\DB::table($t)->where('user_id', $user->id)->delete(); }
}
// a fresh run starts without old attempts
App\Models\Attempt::where('user_id', $user->id)->get()->each(fn ($a) => $a->forceFill(['status' => 'abandoned'])->save());
Entitlement::where('user_id', $user->id)->delete();
$e = new Entitlement();
$e->forceFill(['uuid' => (string) Str::uuid(), 'user_id' => $user->id, 'scope' => 'all_access', 'status' => 'active',
    'source' => 'admin_grant', 'valid_from' => now()->subDay(), 'is_active' => true, 'questions_access' => true,
    'practice_access' => true, 'study_access' => true, 'analytics_access' => true])->save();
$out['learner'] = $user->email;
$out['exams'] = Exam::all(['code', 'slug', 'status', 'duration_minutes', 'question_count'])->toArray();
echo json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
