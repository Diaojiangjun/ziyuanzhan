(function () {
  var toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      var root = document.documentElement;
      var isDark = root.classList.toggle('dark');
      try { localStorage.setItem('theme', isDark ? 'dark' : 'light'); } catch (e) {}
    });
  }

  document.querySelectorAll('[data-copy-target]').forEach(function (button) {
    button.addEventListener('click', function () {
      var target = document.getElementById(button.getAttribute('data-copy-target'));
      if (!target) return;
      var text = target.textContent.trim();
      var done = function () {
        var original = button.textContent;
        button.textContent = '已复制';
        setTimeout(function () { button.textContent = original; }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(done);
      } else {
        var area = document.createElement('textarea');
        area.value = text;
        document.body.appendChild(area);
        area.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(area);
        done();
      }
    });
  });

  var testButtons = document.querySelectorAll('[data-api-test]');
  testButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      var slug = button.getAttribute('data-api-test');
      var box = document.getElementById('test-result');
      if (!box) return;
      box.hidden = false;
      box.innerHTML = '<p class="muted">正在测试接口，请稍候…</p>';
      button.disabled = true;
      fetch('/api/test/' + encodeURIComponent(slug))
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (!data.success) {
            box.innerHTML = '<div class="row"><span>结果</span><span class="red">测试失败</span></div>' +
              '<pre>' + escapeHtml(data.error || '未知错误') + '</pre>';
            return;
          }
          var parts = [
            row('HTTP 状态', data.status_code),
            row('响应耗时', data.elapsed_ms + 'ms'),
            row('接口判定', data.alive ? '可访问' : '不可访问'),
            row('Content-Type', data.content_type || '-')
          ];
          if (data.top_keys && data.top_keys.length) {
            parts.push(row('JSON 顶层字段', data.top_keys.join(', ')));
          }
          if (data.preview) {
            parts.push('<pre>' + escapeHtml(data.preview) + '</pre>');
          }
          box.innerHTML = parts.join('');
        })
        .catch(function (error) {
          box.innerHTML = '<div class="row"><span>结果</span><span class="red">请求失败</span></div>' +
            '<pre>' + escapeHtml(String(error)) + '</pre>';
        })
        .finally(function () { button.disabled = false; });
    });
  });

  document.querySelectorAll('.filter-panel select').forEach(function (select) {
    select.addEventListener('change', function () {
      var form = select.closest('form');
      if (form) form.submit();
    });
  });

  function row(label, value) {
    return '<div class="row"><span>' + escapeHtml(label) + '</span><span>' + escapeHtml(String(value)) + '</span></div>';
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, function (char) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char];
    });
  }
})();
