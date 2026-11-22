// FILE: src/components/proctor/EvidenceGallery.tsx
// Screenshots + clips viewer

'use client';

import { useState } from 'react';
import { Image, Film, X, ChevronLeft, ChevronRight } from 'lucide-react';

interface EvidenceItem {
  id: string;
  type: 'screenshot' | 'clip';
  url: string;
  timestamp: string;
  eventType: string;
  geminiVerdict?: string;
}

interface EvidenceGalleryProps {
  items: EvidenceItem[];
}

export function EvidenceGallery({ items }: EvidenceGalleryProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  if (items.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-600 text-sm">
        No evidence collected yet.
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
        {items.map((item, i) => (
          <div
            key={item.id}
            onClick={() => setSelectedIndex(i)}
            className="relative aspect-video bg-gray-800 rounded-lg overflow-hidden cursor-pointer
                       border border-gray-700 hover:border-gray-500 transition-colors group"
          >
            {item.type === 'screenshot' ? (
              <img src={item.url} alt={item.eventType} className="w-full h-full object-cover" />
            ) : (
              <div className="flex items-center justify-center h-full">
                <Film className="w-6 h-6 text-gray-500 group-hover:text-blue-400 transition-colors" />
              </div>
            )}
            <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-1.5 py-0.5 text-[10px] text-gray-300">
              {item.eventType.replace(/_/g, ' ')}
            </div>
          </div>
        ))}
      </div>

      {/* Lightbox Modal */}
      {selectedIndex !== null && (
        <div className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4">
          <button
            onClick={() => setSelectedIndex(null)}
            className="absolute top-4 right-4 p-2 text-white hover:bg-white/10 rounded-full"
          >
            <X className="w-6 h-6" />
          </button>

          {selectedIndex > 0 && (
            <button
              onClick={() => setSelectedIndex(selectedIndex - 1)}
              className="absolute left-4 p-2 text-white hover:bg-white/10 rounded-full"
            >
              <ChevronLeft className="w-8 h-8" />
            </button>
          )}

          {selectedIndex < items.length - 1 && (
            <button
              onClick={() => setSelectedIndex(selectedIndex + 1)}
              className="absolute right-4 p-2 text-white hover:bg-white/10 rounded-full"
            >
              <ChevronRight className="w-8 h-8" />
            </button>
          )}

          <div className="max-w-4xl w-full">
            {items[selectedIndex].type === 'screenshot' ? (
              <img
                src={items[selectedIndex].url}
                alt={items[selectedIndex].eventType}
                className="w-full rounded-lg"
              />
            ) : (
              <video
                src={items[selectedIndex].url}
                controls
                className="w-full rounded-lg"
              />
            )}
            <div className="mt-4 text-center">
              <p className="text-white font-medium">{items[selectedIndex].eventType.replace(/_/g, ' ')}</p>
              <p className="text-gray-400 text-sm">{new Date(items[selectedIndex].timestamp).toLocaleString()}</p>
              {items[selectedIndex].geminiVerdict && (
                <p className="text-blue-400 text-sm mt-2">
                  AI Verdict: {items[selectedIndex].geminiVerdict}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default EvidenceGallery;
